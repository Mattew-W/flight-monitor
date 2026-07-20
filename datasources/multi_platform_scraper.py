"""
Flight Monitor - Multi-Platform Browser Scraper
Scrapes qunar, fliggy, tongcheng, airline official sites using shared BrowserPool.
"""
import json
import logging
import time
import re
from typing import List, Optional, Dict
from datetime import datetime
from urllib.parse import quote, urlencode
from .base import BaseDataSource
from core.models import FlightPrice, SearchQuery
from core.browser_pool import get_browser_pool
from datasources.flight_schedules import lookup_flight_schedule, get_aircraft_for_flight

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# ── URL builders ───────────────────────────────────────────────

def _qunar_url(dep, arr, date):
    return (
        f"https://flight.qunar.com/site/oneway_list.htm"
        f"?searchDepartureAirport={quote(dep)}"
        f"&searchArrivalAirport={quote(arr)}"
        f"&searchDepartureTime={date}"
    )


def _fliggy_url(dep, arr, date):
    return (
        f"https://s.fliggy.com/flight/search"
        f"?from={quote(dep)}&to={quote(arr)}&date={date}&adult=1&child=0"
    )


def _tongcheng_url(dep, arr, date):
    return (
        f"https://www.ly.com/flights/itinerary/oneway/{quote(dep)}-{quote(arr)}"
        f"?date={date}"
    )


def _airline_url_airchina(dep, arr, date):
    return (
        f"https://www.airchina.com.cn/swp/index/flightSearch"
        f"?tripType=0&depCity={quote(dep)}&arrCity={quote(arr)}"
        f"&depDate={date}&cabin=y_s"
    )


PLATFORM_URL_BUILDERS = {
    "qunar": _qunar_url,
    "fliggy": _fliggy_url,
    "tongcheng": _tongcheng_url,
    "airchina": _airline_url_airchina,
}


# ── Multi-Platform Scraper ─────────────────────────────────────

class MultiPlatformScraper(BaseDataSource):
    """Scrape prices from multiple platforms using shared browser."""

    name: str = "multi_platform"

    def __init__(self, platform: str):
        super().__init__()
        self.platform = platform
        self.url_builder = PLATFORM_URL_BUILDERS.get(platform)
        if not self.url_builder:
            raise ValueError(f"Unknown platform: {platform}")

    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT and self.url_builder is not None

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Sync path is NOT supported — browser pool is async-only.
        Use ``AsyncMultiPlatformScraper`` (from async_adapters) instead."""
        raise NotImplementedError(
            f"MultiPlatformScraper({self.platform}) does not support sync calls. "
            f"Use AsyncMultiPlatformScraper from datasources.async_adapters."
        )

    def _extract_prices_from_html(self, html: str, page_url: str, query: SearchQuery) -> List[FlightPrice]:
        """Try multiple strategies to extract prices from rendered HTML.

        Pure sync parsing: accepts HTML string (not page object) so it can be
        called from both sync and async contexts.
        """
        results = []
        try:
            # Strategy 1: Find any element with flight + price pattern in HTML
            # Generic regex: flight number (2 letters + 2-4 digits) + price (¥xxx)
            pattern = re.compile(
                r'([A-Z]{2}\d{2,4})[^¥]{0,80}?¥\s*(\d{3,6})',
                re.DOTALL,
            )
            seen = set()
            for m in pattern.finditer(html):
                flight_no, price_str = m.group(1), m.group(2)
                key = f"{flight_no}_{price_str}"
                if key in seen:
                    continue
                seen.add(key)
                try:
                    price = float(price_str)
                    if price < 100 or price > 99999:
                        continue
                    # Lookup static schedule to fill missing fields
                    sched = lookup_flight_schedule(flight_no)
                    results.append(FlightPrice(
                        query_id=query.id or 0,
                        airline=sched.get("airline", "") if sched else "",
                        flight_no=flight_no,
                        aircraft=sched.get("aircraft", "") if sched else "",
                        departure_time=sched.get("dep", "") if sched else "",
                        arrival_time=sched.get("arr", "") if sched else "",
                        departure_airport=sched.get("dep_airport", query.departure) if sched else query.departure,
                        arrival_airport=sched.get("arr_airport", query.destination) if sched else query.destination,
                        duration=f"{sched['duration_min'] // 60}h{sched['duration_min'] % 60}m" if sched else "",
                        stops=0,
                        price=price,
                        cabin_class=query.cabin_class or "economy",
                        source=self.platform,
                        recorded_at=datetime.now().isoformat(),
                        purchase_url=page_url,
                        is_mock=False,
                        sub_class="Y",
                        seat_inventory=0,
                    ))
                    if len(results) >= 30:
                        break
                except (ValueError, TypeError):
                    continue
        except Exception as e:
            logger.debug(f"[{self.platform}] extraction error: {e}")
        return results


# ── Source wrappers for monitor integration ─────────────────────

class QunarSource(MultiPlatformScraper):
    name = "qunar"
    def __init__(self):
        super().__init__("qunar")


class FliggySource(MultiPlatformScraper):
    name = "fliggy"
    def __init__(self):
        super().__init__("fliggy")


class TongchengSource(MultiPlatformScraper):
    name = "tongcheng"
    def __init__(self):
        super().__init__("tongcheng")


class AirChinaSource(MultiPlatformScraper):
    name = "airchina"
    def __init__(self):
        super().__init__("airchina")
