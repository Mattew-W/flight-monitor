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
from datasources import (
    MockDataSource, CtripDataSource,
    CtripBrowserSource, SkyscannerSource,
    BingSearchSource,
)
from datasources.async_adapters import AsyncBingSearchSource
from config import (
    MONITOR_INTERVAL_SECONDS, ENABLED_SOURCES,
    SOURCE_PRIORITY, CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT, CIRCUIT_BREAKER_SUCCESS_THRESHOLD,
)

logger = logging.getLogger(__name__)

# ── Notification worker ─────────────────────────────────────────
_MAX_NOTIFY_QUEUE = 200
_NOTIFY_WORKERS = 2


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
                send_email: bool, send_wechat: bool,
                query_id: Optional[int] = None, price: Optional[float] = None):
        try:
            self._queue.put_nowait((title, message, send_email, send_wechat,
                                    query_id, price))
        except queue.Full:
            logger.warning("Notify queue full, dropping notification")

    def _run(self):
        while self._running or not self._queue.empty():
            try:
                title, message, send_email, send_wechat, qid, price = self._queue.get(timeout=2)
                self._notifier.send_notification(
                    title=title, message=message,
                    send_email=send_email, send_wechat=send_wechat,
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
        """Build the source chain with priorities and circuit breakers."""
        # Define source factory functions
        source_factories = {
            "mock": lambda: MockDataSource(),
            "ctrip": lambda: CtripDataSource(),
            "ctrip_browser": lambda: CtripBrowserSource(),
            "skyscanner": lambda: SkyscannerSource(),
            "bing": lambda: AsyncBingSearchSource(),
        }

        # Add sources in priority order
        for name in sorted(SOURCE_PRIORITY, key=lambda k: SOURCE_PRIORITY[k]):
            if name not in ENABLED_SOURCES:
                continue
            if name not in source_factories:
                continue

            try:
                src = source_factories[name]()
                # Check availability (skip circuit breaker for mock - always available)
                if name != "mock" and hasattr(src, 'is_available') and not src.is_available():
                    logger.info(f"Source '{name}' not available, skipping")
                    continue

                # Wrap in async adapter if needed
                wrapped = self._wrap_source(src)
                priority = SOURCE_PRIORITY[name]

                # Mock source: no circuit breaker (always works)
                cb = None if name == "mock" else cb_config
                self.source_chain.add_source(wrapped, priority=priority,
                                             circuit_breaker_config=cb)
            except Exception as e:
                logger.warning(f"Failed to initialize source '{name}': {e}")

        if len(self.source_chain) == 0:
            # Ensure mock is always available as ultimate fallback
            logger.warning("No sources configured, adding mock as fallback")
            self.source_chain.add_source(
                self._wrap_source(MockDataSource()),
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
        self._notify_worker.stop()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
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
        queries = self.db.get_monitoring_queries()
        if not queries:
            return
        n = len(queries)
        workers = min(n, self.max_workers)
        logger.info(f"Checking {n} monitoring queries ({workers} workers)...")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self.check_query, q): q for q in queries}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    q = futures[future]
                    logger.error(f"Error checking query {q.id}: {e}")

    def check_query(self, query: SearchQuery) -> List[FlightPrice]:
        """Check prices for a single query and store results.

        S1: Uses a single asyncio.run() to coordinate all sources uniformly,
        avoiding per-source event loop creation.
        """
        return asyncio.run(self._check_query_async(query))

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
            query_id=query.id, price=flight.price,
        )

    def search_once(self, query: SearchQuery) -> List[FlightPrice]:
        """One-shot search across all sources. S1: single asyncio.run()."""
        return asyncio.run(self._search_once_async(query))

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
