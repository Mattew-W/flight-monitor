"""
Flight Monitor - Price Monitoring Engine v2
Concurrent query checking + async notification queue.
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
from datasources import (
    MockDataSource, CtripDataSource,
    CtripBrowserSource, SkyscannerSource,
    BingSearchSource,
)
from config import (
    MONITOR_INTERVAL_SECONDS, ENABLED_SOURCES,
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

        # Initialize data sources
        self.sources = {}
        if "mock" in ENABLED_SOURCES:
            self.sources["mock"] = MockDataSource()
        if "ctrip" in ENABLED_SOURCES:
            src = CtripDataSource()
            if src.is_available():
                self.sources["ctrip"] = src
        if "ctrip_browser" in ENABLED_SOURCES:
            src = CtripBrowserSource()  # async v4: uses shared browser pool
            if src.is_available():
                self.sources["ctrip_browser"] = src
        if "skyscanner" in ENABLED_SOURCES:
            src = SkyscannerSource()
            if src.is_available():
                self.sources["skyscanner"] = src
        if "bing" in ENABLED_SOURCES:
            src = BingSearchSource()
            if src.is_available():
                self.sources["bing"] = src

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

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
        """Check prices for a single query and store results."""
        all_prices: List[FlightPrice] = []

        for source_name, source in self.sources.items():
            try:
                # Auto-detect async sources (e.g. ctrip_browser) and run them
                # in a temporary event loop within the threadpool worker.
                sf = source.search_flights
                if inspect.iscoroutinefunction(sf):
                    prices = asyncio.run(sf(query))
                else:
                    prices = sf(query)
                if prices:
                    # Filter out records with invalid price (None / NaN / non-positive)
                    # so downstream min()/sort()/alert comparisons don't crash.
                    valid = [p for p in prices
                             if p.price is not None
                             and p.price == p.price  # NaN check
                             and p.price > 0]
                    dropped = len(prices) - len(valid)
                    if dropped:
                        logger.warning(
                            f"  [{source_name}] dropped {dropped} invalid-price records"
                        )
                    if valid:
                        all_prices.extend(valid)
                        logger.info(
                            f"  [{source_name}] {query.departure}->{query.destination} "
                            f"on {query.departure_date}: {len(valid)} flights, "
                            f"min ¥{min(p.price for p in valid):.0f}"
                        )
            except Exception as e:
                logger.error(f"  [{source_name}] Error: {e}")

        if not all_prices and "mock" in self.sources:
            logger.info("  No real data, falling back to mock...")
            try:
                prices = self.sources["mock"].search_flights(query)
                if prices:
                    valid = [p for p in prices
                             if p.price is not None and p.price == p.price and p.price > 0]
                    if valid:
                        all_prices.extend(valid)
                        logger.info(f"  [mock fallback] {len(valid)} flights")
            except Exception as e:
                logger.error(f"  [mock fallback] Error: {e}")

        if all_prices:
            self.db.add_price_records(all_prices)
            self._check_alerts(query, all_prices)

        return all_prices

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
        all_prices: List[FlightPrice] = []
        for source_name, source in self.sources.items():
            try:
                sf = source.search_flights
                prices = asyncio.run(sf(query)) if inspect.iscoroutinefunction(sf) else sf(query)
                all_prices.extend(prices)
            except Exception as e:
                logger.error(f"[{source_name}] Error: {e}")
        # Sort safely: filter out None/NaN prices first.
        valid = [p for p in all_prices if p.price is not None and p.price == p.price]
        valid.sort(key=lambda p: p.price)
        return valid

    def search_and_store(self, query: SearchQuery) -> List[FlightPrice]:
        return self.check_query(query)
