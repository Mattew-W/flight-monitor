"""
Flight Monitor - Price Monitoring Engine
Periodically checks flight prices and triggers alerts when thresholds are met.
"""
import logging
import threading
import time
from datetime import datetime
from typing import List, Optional
from .database import Database
from .models import SearchQuery, FlightPrice, PriceAlert, AlertHistory
from .notifier import Notifier
from datasources import (
    MockDataSource, CtripDataSource,
    CtripBrowserSource, SkyscannerSource,
)
from config import (
    MONITOR_INTERVAL_SECONDS, ENABLED_SOURCES,
    CTRIP_FRESH_PER_SEARCH, CTRIP_PROXY,
)

logger = logging.getLogger(__name__)


class PriceMonitor:
    """Background price monitoring engine."""

    def __init__(self, db: Database, interval: int = MONITOR_INTERVAL_SECONDS):
        self.db = db
        self.interval = interval
        self.notifier = Notifier()

        # Initialize data sources
        self.sources = {}
        if "mock" in ENABLED_SOURCES:
            self.sources["mock"] = MockDataSource()
        if "ctrip" in ENABLED_SOURCES:
            src = CtripDataSource()
            if src.is_available():
                self.sources["ctrip"] = src
        if "ctrip_browser" in ENABLED_SOURCES:
            src = CtripBrowserSource(fresh_per_search=CTRIP_FRESH_PER_SEARCH,
                                     proxy=CTRIP_PROXY)
            if src.is_available():
                self.sources["ctrip_browser"] = src
        if "skyscanner" in ENABLED_SOURCES:
            src = SkyscannerSource()
            if src.is_available():
                self.sources["skyscanner"] = src

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()

    def start(self):
        """Start the monitoring thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"Price monitor started (interval={self.interval}s)")

    def stop(self):
        """Stop the monitoring thread."""
        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Price monitor stopped")

    def _run_loop(self):
        """Main monitoring loop with interruptible sleep."""
        while not self._stop_event.is_set():
            try:
                self._check_all()
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            # Interruptible sleep using Event.wait()
            self._stop_event.wait(timeout=self.interval)

    def _check_all(self):
        """Check all monitoring queries."""
        queries = self.db.get_monitoring_queries()
        if not queries:
            return
        logger.info(f"Checking {len(queries)} monitoring queries...")
        for query in queries:
            try:
                self.check_query(query)
            except Exception as e:
                logger.error(f"Error checking query {query.id}: {e}")

    def check_query(self, query: SearchQuery) -> List[FlightPrice]:
        """Check prices for a single query and store results.
        Tries real data sources first, falls back to mock if needed.
        Returns the list of fetched prices.
        """
        all_prices: List[FlightPrice] = []

        # Try each enabled source
        for source_name, source in self.sources.items():
            try:
                prices = source.search_flights(query)
                if prices:
                    all_prices.extend(prices)
                    logger.info(
                        f"  [{source_name}] {query.departure}->{query.destination} "
                        f"on {query.departure_date}: {len(prices)} flights, "
                        f"min ¥{min(p.price for p in prices):.0f}"
                    )
            except Exception as e:
                logger.error(f"  [{source_name}] Error: {e}")

        # If no real data, use mock as fallback
        if not all_prices and "mock" in self.sources:
            logger.info("  No real data, falling back to mock...")
            try:
                prices = self.sources["mock"].search_flights(query)
                if prices:
                    all_prices.extend(prices)
                    logger.info(f"  [mock fallback] {len(prices)} flights")
            except Exception as e:
                logger.error(f"  [mock fallback] Error: {e}")

        if all_prices:
            # Store all price records
            self.db.add_price_records(all_prices)
            # Check alerts
            self._check_alerts(query, all_prices)

        return all_prices

    def _check_alerts(self, query: SearchQuery, prices: List[FlightPrice]):
        """Check if any alerts should be triggered for this query."""
        if not prices:
            return

        alerts = self.db.get_alerts(query.id)
        if not alerts:
            return

        min_price = min(p.price for p in prices)
        cheapest = min(prices, key=lambda p: p.price)

        for alert in alerts:
            if not alert.is_active:
                continue
            if min_price <= alert.target_price:
                self._trigger_alert(alert, query, cheapest)
            else:
                logger.info(
                    f"  Alert {alert.id}: min ¥{min_price:.0f} > target ¥{alert.target_price:.0f}"
                )

    def _trigger_alert(self, alert: PriceAlert, query: SearchQuery, flight: FlightPrice):
        """Trigger a price alert notification."""
        logger.info(
            f"  *** ALERT TRIGGERED *** Alert {alert.id}: "
            f"¥{flight.price:.0f} <= ¥{alert.target_price:.0f}"
        )

        # Record in alert history
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
            alert_id=alert.id or 0,
            query_id=query.id or 0,
            price=flight.price,
            target_price=alert.target_price,
            airline=flight.airline,
            flight_no=flight.flight_no,
            message=message,
        )
        self.db.add_alert_history(hist)
        self.db.mark_alert_triggered(alert.id or 0)

        # Send notification
        title = f"✈️ 机票降价提醒: {query.departure}→{query.destination} ¥{flight.price:.0f}"
        self.notifier.send_notification(
            title=title,
            message=message,
            send_email=alert.notify_email,
            send_wechat=alert.notify_wechat,
        )

    def search_once(self, query: SearchQuery) -> List[FlightPrice]:
        """Perform a one-time search (not stored)."""
        all_prices: List[FlightPrice] = []
        for source_name, source in self.sources.items():
            try:
                prices = source.search_flights(query)
                all_prices.extend(prices)
            except Exception as e:
                logger.error(f"[{source_name}] Error: {e}")
        all_prices.sort(key=lambda p: p.price)
        return all_prices

    def search_and_store(self, query: SearchQuery) -> List[FlightPrice]:
        """Search and store results (for manual trigger)."""
        prices = self.check_query(query)
        return prices
