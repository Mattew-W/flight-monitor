"""
Flight Monitor - Price Monitoring Engine v3
Concurrent query checking + async notification queue.
S1: Uses async adapters for uniform sync/async source handling.
S4: Uses SourceChain + CircuitBreaker for priority-based fallback.
"""
import asyncio
import inspect
import logging
import threading
import time
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional

from .database import Database
from .models import SearchQuery, FlightPrice, PriceAlert, AlertHistory
from .notifier import Notifier
from .async_scraper_base import AsyncScraperBase
from .source_chain import SourceChain
from .circuit_breaker import CircuitBreakerConfig
from .model_store import ModelStore
from config import (
    MONITOR_INTERVAL_SECONDS, ENABLED_SOURCES,
    SOURCE_PRIORITY, CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT, CIRCUIT_BREAKER_SUCCESS_THRESHOLD,
)

logger = logging.getLogger(__name__)

# ── Notification worker ─────────────────────────────────────────
_MAX_NOTIFY_QUEUE = 200
_NOTIFY_WORKERS = 2


class _AsyncEventLoopThread:
    """Background thread running a dedicated asyncio event loop.

    This allows calling async code safely from sync Flask routes
    without creating/destroying event loops per call (which is slow)
    and without RuntimeError when called from an async context
    (which asyncio.run() would cause).
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._started.wait(timeout=5)

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def run(self, coro):
        """Submit a coroutine to the event loop and block until done."""
        if self._loop is None:
            # Lazy-start: allows search_once() etc. to work even when the
            # monitor loop was never started (no monitoring queries at boot).
            self.start()
        if self._loop is None:
            raise RuntimeError("Event loop thread failed to start")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=120)

    def stop(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
            self._loop = None


class _NotifyWorker:
    """Background worker that consumes notification tasks from a queue.

    This decouples the I/O-heavy notification sending (SMTP, HTTP)
    from the main monitor loop, preventing blocking.
    """

    def __init__(self, notifier: Notifier):
        self._queue: queue.Queue = queue.Queue(maxsize=_MAX_NOTIFY_QUEUE)
        self._notifier = notifier
        self._workers = []
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            for _ in range(_NOTIFY_WORKERS):
                t = threading.Thread(target=self._run, daemon=True)
                t.start()
                self._workers.append(t)

    def stop(self):
        with self._lock:
            if not self._running:
                # Already stopped; just make sure workers are joined.
                pass
            self._running = False
        # Give workers a chance to drain the queue BEFORE joining.
        # Previously we dropped pending tasks, which silently lost price alerts.
        for t in self._workers:
            t.join(timeout=5)
        self._workers.clear()

    def enqueue(self, title: str, message: str,
                send_email: bool, send_wechat: bool, send_feishu: bool = True,
                query_id: Optional[int] = None, price: Optional[float] = None):
        try:
            self._queue.put_nowait((title, message, send_email, send_wechat, send_feishu,
                                    query_id, price))
        except queue.Full:
            logger.warning("Notify queue full, dropping notification")

    def _run(self):
        while self._running or not self._queue.empty():
            try:
                title, message, send_email, send_wechat, send_feishu, qid, price = self._queue.get(timeout=2)
                self._notifier.send_notification(
                    title=title, message=message,
                    send_email=send_email, send_wechat=send_wechat, send_feishu=send_feishu,
                    query_id=qid, price=price,
                )
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Notify worker error: {e}")


# ── Source Adapters (uniform async interface) ───────────────────

class _SyncToAsyncAdapter(AsyncScraperBase):
    """Wraps a sync-only source into AsyncScraperBase interface."""

    def __init__(self, source):
        self._source = source
        self.name = getattr(source, 'name', source.__class__.__name__)

    def is_available(self) -> bool:
        return self._source.is_available()

    def _sync_search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        return self._source.search_flights(query)


class _AsyncMethodAdapter(AsyncScraperBase):
    """Wraps a source that has async search_flights() into AsyncScraperBase."""

    def __init__(self, source):
        self._source = source
        self.name = getattr(source, 'name', source.__class__.__name__)

    def is_available(self) -> bool:
        return self._source.is_available()

    async def async_search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        return await self._source.search_flights(query)


# ── Price Monitor (concurrent) ──────────────────────────────────

class PriceMonitor:
    """Background price monitoring engine with concurrent execution."""

    def __init__(self, db: Database, interval: int = MONITOR_INTERVAL_SECONDS,
                 max_workers: int = 4):
        self.db = db
        self.interval = interval
        self.max_workers = max_workers
        self.notifier = Notifier()
        self._notify_worker = _NotifyWorker(self.notifier)
        self._async_loop = _AsyncEventLoopThread()
        self.model_store = ModelStore()

        # S4: Build SourceChain with circuit breakers
        self.source_chain = SourceChain("monitor")
        cb_config = CircuitBreakerConfig(
            failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            recovery_timeout=CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
            success_threshold=CIRCUIT_BREAKER_SUCCESS_THRESHOLD,
        )
        self._build_source_chain(cb_config)

        # Keep sources dict for backward compatibility (stats, inspection)
        self.sources = {}
        for name, entry in zip(
            self.source_chain.get_source_names(),
            self.source_chain._sources
        ):
            self.sources[name] = entry.source

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def _build_source_chain(self, cb_config: CircuitBreakerConfig):
        """Build the source chain from the registered sources.

        Priority order comes from ``SOURCE_PRIORITY``; availability is
        checked via ``is_available()``; each source is auto-wrapped for
        sync/async uniformity.
        """
        from datasources.base import create_source, list_sources

        # Determine which sources to enable
        enabled = ENABLED_SOURCES or list_sources().keys()

        for name in sorted(enabled, key=lambda k: SOURCE_PRIORITY.get(k, 99)):
            if name not in SOURCE_PRIORITY:
                continue
            try:
                src = create_source(name)
                # Skip unavailable sources (but allow mock)
                if name != "mock" and hasattr(src, 'is_available') and not src.is_available():
                    logger.info(f"Source '{name}' not available, skipping")
                    continue

                wrapped = self._wrap_source(src)
                priority = SOURCE_PRIORITY[name]

                # Mock source: no circuit breaker (always works)
                cb = None if name == "mock" else cb_config
                self.source_chain.add_source(wrapped, priority=priority,
                                             circuit_breaker_config=cb)
            except Exception as e:
                logger.warning(f"Failed to initialize source '{name}': {e}")

        if len(self.source_chain) == 0:
            logger.warning("No sources configured, adding mock as fallback")
            self.source_chain.add_source(
                self._wrap_source(create_source("mock")),
                priority=99, circuit_breaker_config=None
            )

    @staticmethod
    def _wrap_source(source) -> AsyncScraperBase:
        """Wrap any source into a uniform async adapter.

        - Sources with async_search_flights → returned as-is
        - Sources with async search_flights → wrapped in _AsyncMethodAdapter
        - Sources with sync search_flights → wrapped in _SyncToAsyncAdapter
        """
        if hasattr(source, 'async_search_flights'):
            return source
        if hasattr(source, 'search_flights'):
            if inspect.iscoroutinefunction(source.search_flights):
                return _AsyncMethodAdapter(source)
            return _SyncToAsyncAdapter(source)
        # Fallback: wrap in generic adapter
        return _SyncToAsyncAdapter(source)

    @property
    def is_running(self) -> bool:
        """Public read-only accessor for the monitor's running state."""
        return self._running

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._async_loop.start()
            self._notify_worker.start()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info(f"Price monitor started (interval={self.interval}s, "
                        f"workers={self.max_workers})")

    def stop(self):
        with self._lock:
            if not self._running and self._thread is None:
                return
            self._running = False
        self._stop_event.set()
        # Join the monitor loop thread FIRST so it stops enqueuing
        # notifications before we shut down the notify workers.
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        # Now safe to stop workers (no new tasks will arrive).
        self._notify_worker.stop()
        self._async_loop.stop()
        # Shut down the monitor thread pool (if any) to avoid thread leaks.
        if hasattr(self, "_pool"):
            self._pool.shutdown(wait=False)
            self._pool = None
        logger.info("Price monitor stopped")

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self._check_all_concurrent()
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            self._stop_event.wait(timeout=self.interval)

    def _check_all_concurrent(self):
        """Check all monitoring queries in parallel using ThreadPoolExecutor."""
        # Reuse a fixed worker pool across cycles instead of creating a new
        # ThreadPoolExecutor each period. Per-cycle creation leaks thread-local
        # SQLite connections (they linger in db._all_conns after the thread dies).
        if not hasattr(self, "_pool"):
            self._pool = ThreadPoolExecutor(max_workers=self.max_workers,
                                            thread_name_prefix="monitor")

        queries = self.db.get_monitoring_queries()
        if not queries:
            return
        n = len(queries)
        workers = min(n, self.max_workers)
        logger.info(f"Checking {n} monitoring queries ({workers} workers)...")

        futures = {self._pool.submit(self.check_query, q): q for q in queries}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                q = futures[future]
                logger.error(f"Error checking query {q.id}: {e}")

    def check_query(self, query: SearchQuery) -> List[FlightPrice]:
        """Check prices for a single query and store results.

        S1: Uses the persistent event loop thread to coordinate all sources,
        avoiding per-call event loop creation and working safely from both
        sync and async Flask routes.
        """
        return self._async_loop.run(self._check_query_async(query))

    async def _check_query_async(self, query: SearchQuery) -> List[FlightPrice]:
        """S4: Use SourceChain for priority-based fallback with circuit breakers.

        The chain tries sources in priority order. First source that returns
        valid results is used. If all fail, mock (priority 99) provides fallback.
        """
        prices = await self.source_chain.search(query)

        # Filter out records with invalid price (None / NaN / non-positive)
        if prices:
            valid = [p for p in prices
                     if p.price is not None
                     and p.price == p.price  # NaN check
                     and p.price > 0]
            dropped = len(prices) - len(valid)
            if dropped:
                logger.warning(f"  Dropped {dropped} invalid-price records")
            prices = valid

        if prices:
            logger.info(
                f"  {query.departure}->{query.destination} "
                f"on {query.departure_date}: {len(prices)} flights, "
                f"min ¥{min(p.price for p in prices):.0f}"
            )
            self.db.add_price_records(prices)
            self._check_alerts(query, prices)
        else:
            logger.info(
                f"  {query.departure}->{query.destination} "
                f"on {query.departure_date}: no results from any source"
            )

        return prices

    def _check_alerts(self, query: SearchQuery, prices: List[FlightPrice]):
        if not prices:
            return
        alerts = self.db.get_alerts(query.id)
        if not alerts:
            return
        # Guard: all prices already validated in check_query, but double-check here.
        valid_prices = [p for p in prices if p.price is not None and p.price == p.price]
        if not valid_prices:
            return
        min_price = min(p.price for p in valid_prices)
        cheapest = min(valid_prices, key=lambda p: p.price)

        for alert in alerts:
            if not alert.is_active:
                continue
            if alert.id is None:
                logger.warning(f"  Skipping alert with None id for query {query.id}")
                continue
            if min_price <= alert.target_price:
                self._trigger_alert(alert, query, cheapest)

    def _trigger_alert(self, alert: PriceAlert, query: SearchQuery,
                       flight: FlightPrice):
        logger.info(
            f"  *** ALERT TRIGGERED *** Alert {alert.id}: "
            f"¥{flight.price:.0f} <= ¥{alert.target_price:.0f}"
        )
        message = (
            f"降价提醒！{query.departure} → {query.destination} "
            f"({query.departure_date})\n"
            f"当前最低价: ¥{flight.price:.0f}\n"
            f"目标价格: ¥{alert.target_price:.0f}\n"
            f"航班: {flight.airline} {flight.flight_no}\n"
            f"时间: {flight.departure_time} - {flight.arrival_time}\n"
            f"机型: {flight.aircraft}"
        )
        hist = AlertHistory(
            alert_id=alert.id or 0, query_id=query.id or 0,
            price=flight.price, target_price=alert.target_price,
            airline=flight.airline, flight_no=flight.flight_no,
            message=message,
        )
        self.db.add_alert_history(hist)
        self.db.mark_alert_triggered(alert.id or 0)

        title = f"✈️ 机票降价提醒: {query.departure}→{query.destination} ¥{flight.price:.0f}"
        # Send via async queue (non-blocking). Pass query_id + price so the notifier
        # can dedup: same route + same price band won't fire more than once per hour.
        self._notify_worker.enqueue(
            title=title, message=message,
            send_email=alert.notify_email, send_wechat=alert.notify_wechat,
            send_feishu=alert.notify_feishu,
            query_id=query.id, price=flight.price,
        )

    def search_once(self, query: SearchQuery) -> List[FlightPrice]:
        """One-shot search across all sources. S1: uses persistent event loop."""
        return self._async_loop.run(self._search_once_async(query))

    async def _search_once_async(self, query: SearchQuery) -> List[FlightPrice]:
        """S4: Use SourceChain.search_all() for maximum coverage.

        Unlike monitoring (which uses fallback), one-shot search aggregates
        results from all available sources for price comparison.
        """
        prices = await self.source_chain.search_all(query)
        # Sort safely: filter out None/NaN prices first.
        valid = [p for p in prices if p.price is not None and p.price == p.price]
        valid.sort(key=lambda p: p.price)
        return valid

    def search_and_store(self, query: SearchQuery) -> List[FlightPrice]:
        return self.check_query(query)

    def get_chain_status(self) -> dict:
        """S4: Return source chain status including circuit breakers and stats."""
        return {
            "chain_name": self.source_chain.name,
            "sources": self.source_chain.get_source_names(),
            "stats": self.source_chain.get_stats(),
            "circuit_breakers": self.source_chain.get_circuit_breaker_info(),
        }

    # ── M4: Model Training & Persistence ───────────────────────

    def train_and_save_model(self, query_id: int) -> dict:
        """Train a new model version for a query and persist it.

        Called after data collection (manual or automatic). Builds training
        data from historical prices, fits PricePredictorV3 online model,
        evaluates with walk-forward backtest, and saves a new version.

        Returns dict with version number, metrics, and status.
        """
        from core.predictor import PricePredictorV3
        from core.price_prediction import HolidayManager

        q = self.db.get_query(query_id)
        if not q:
            return {"error": "Query not found"}

        # 1. Gather historical records for training
        # CRITICAL: Use real-only data. Mock prices would pollute the labels
        # and degrade model quality.
        historical = self.db.get_daily_cheapest_records(
            query_id=query_id, real_only=True, include_mock=False, limit=500,
        )
        if len(historical) < 10:
            return {
                "status": "insufficient_data",
                "message": f"Need ≥10 records, got {len(historical)}. Collect more data first.",
                "records_found": len(historical),
            }

        # 2. Build training records for predictor
        holidays = HolidayManager.get_holidays(
            datetime.strptime(q.departure_date, "%Y-%m-%d").year
        )
        holidays_list = [(s, e) for s, e, _ in holidays]

        online_history = []
        for h in historical:
            online_history.append({
                "price": float(h["price"]),
                "date": h["date"],
                "departure_time": h.get("departure_time", ""),
                "sub_class": h.get("sub_class", ""),
                "seat_inventory": int(h.get("seat_inventory", 9)),
                "stops": int(h.get("stops", 0)),
                "is_mock": h.get("source", "") not in ["ctrip_browser"],
            })

        # 3. Initialize predictor and train
        predictor = PricePredictorV3()
        X, y = predictor.build_training_data(
            historical_records=online_history,
            departure=q.departure,
            destination=q.destination,
            holidays=holidays_list,
            departure_date=q.departure_date,
        )

        if not X or len(X) < 10:
            return {
                "status": "insufficient_data",
                "message": f"Only {len(X)} training samples after feature extraction. Need ≥10.",
            }

        predictor.fit_online(X, y)

        # 4. Evaluate with walk-forward backtest
        backtest = predictor.backtest_walk_forward(
            records=online_history,
            departure_city=q.departure,
            destination_city=q.destination,
            holidays=holidays_list,
            n_splits=min(5, len(online_history) // 10),
            min_train_size=10,
            purge_gap=1,
            departure_date=q.departure_date,
        )

        metrics = {
            "r2": backtest.get("r2", 0),
            "rmse": backtest.get("rmse", 0),
            "mae": backtest.get("mae", 0),
            "mape": backtest.get("mape", 0),
            "n_predictions": backtest.get("n_predictions", 0),
        }

        # 5. Save new version
        version = self.model_store.save_version(
            query_id=query_id,
            predictor=predictor,
            metrics=metrics,
            description=f"Auto-trained on {len(online_history)} records",
        )

        logger.info(
            f"Model trained & saved: query={query_id} v{version} "
            f"(R²={metrics['r2']:.3f}, RMSE={metrics['rmse']:.0f})"
        )

        return {
            "status": "ok",
            "version": version,
            "metrics": metrics,
            "records_used": len(online_history),
        }
