"""
Flight Monitor - Async Adapters (S1 Framework)
================================================
Wraps existing sync scrapers into async interfaces.

This file provides async-compatible wrappers for scrapers that:
  1. Use sync_playwright (bing_search_source, multi_airline_scraper)
  2. Call async browser_pool synchronously (multi_platform_scraper, airline_sniffer)

Usage:
    # Instead of:
    scraper = MultiPlatformScraper("qunar")
    prices = scraper.search_flights(query)  # BUG: calls async pool synchronously

    # Use:
    from datasources.async_adapters import AsyncMultiPlatformScraper
    scraper = AsyncMultiPlatformScraper("qunar")
    prices = await scraper.async_search_flights(query)  # Correct: awaits async pool
"""

import asyncio
import inspect
import logging
from typing import List

from core.models import FlightPrice, SearchQuery
from core.async_scraper_base import AsyncScraperBase, AsyncBrowserScraperBase

logger = logging.getLogger(__name__)


# ── MultiPlatformScraper Async Adapter ─────────────────────────

class AsyncMultiPlatformScraper(AsyncBrowserScraperBase):
    """Async adapter for MultiPlatformScraper.

    Fixes the bug where sync code called get_browser_pool() without awaiting.
    This adapter properly awaits the async browser pool.
    """

    def __init__(self, platform: str):
        from datasources.multi_platform_scraper import MultiPlatformScraper
        self._sync_scraper = MultiPlatformScraper(platform)
        self.name = platform

    def is_available(self) -> bool:
        return self._sync_scraper.is_available()

    async def _async_search_impl(self, query: SearchQuery) -> List[FlightPrice]:
        """Run the sync scraper logic with proper async pool access."""
        from core.browser_pool import get_browser_pool

        pool = await get_browser_pool()
        if pool is None:
            return []

        page = await pool.new_page(self.name)
        if page is None:
            return []

        try:
            # Use the sync scraper's URL builder and extraction logic
            url = self._sync_scraper.url_builder(
                query.departure, query.destination, query.departure_date
            )
            logger.info(f"[{self.name}] Loading {url[:80]}...")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                logger.warning(f"[{self.name}] goto failed: {e}")
                return []

            await page.wait_for_timeout(4000)
            # Await content() to get HTML string, then parse via pure sync function.
            # (sync scraper's _extract_prices can't handle async page object.)
            try:
                html = await page.content()
            except Exception as e:
                logger.warning(f"[{self.name}] content() failed: {e}")
                html = ""
            return self._sync_scraper._extract_prices_from_html(html, page.url, query)
        except Exception as e:
            logger.error(f"[{self.name}] scrape error: {e}")
            return []
        finally:
            await pool.close_page(page)


# ── AirlineSnifferSource Async Adapter ─────────────────────────

class AsyncAirlineSnifferSource(AsyncBrowserScraperBase):
    """Async adapter for AirlineSnifferSource.

    Fixes the bug where sync code called get_browser_pool() without awaiting.
    """

    def __init__(self, airline_key: str):
        from datasources.airline_sniffer import AirlineSnifferSource
        self._sync_scraper = AirlineSnifferSource(airline_key)
        self.name = f"{airline_key}_sniffer"

    def is_available(self) -> bool:
        return self._sync_scraper.is_available()

    async def _async_search_impl(self, query: SearchQuery) -> List[FlightPrice]:
        """Run the sniffer with proper async pool access."""
        from core.browser_pool import get_browser_pool
        from datasources.airline_sniffer import (
            AIRLINE_CONFIGS, _find_flight_list, _normalize_flight,
        )

        pool = await get_browser_pool()
        if pool is None:
            return []

        cfg = AIRLINE_CONFIGS.get(self._sync_scraper._key)
        if cfg is None:
            return []

        city_map = cfg["city_map"]
        dep_code = city_map.get(query.departure, query.departure)
        arr_code = city_map.get(query.destination, query.destination)
        url = cfg["search_url"].format(dep=dep_code, arr=arr_code, date=query.departure_date)

        page = await pool.new_page(self._sync_scraper._key)
        if page is None:
            return []

        # Collect response objects; response.json() is async, so we must await
        # them after navigation completes (can't await inside sync callback).
        _captured_responses = []

        def capture_json(response):
            if response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct:
                    _captured_responses.append(response)

        try:
            await page.set_viewport_size({"width": 375, "height": 812})
            page.on("response", capture_json)
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(10000)
            page.remove_listener("response", capture_json)
        except Exception as e:
            logger.warning(f"[{self._sync_scraper._key}] Browser error: {e}")
            await pool.close_page(page)
            return []

        # Await all captured responses BEFORE closing the page
        # (response body needs the page to stay alive).
        all_json_responses = []
        for resp in _captured_responses:
            try:
                all_json_responses.append(await resp.json())
            except Exception:
                pass

        # Now safe to close the page.
        await pool.close_page(page)

        # Parse captured JSON (sync CPU work, no need for thread)
        results = []
        for data in all_json_responses:
            flight_list = _find_flight_list(data)
            if flight_list:
                for item in flight_list:
                    if isinstance(item, dict):
                        flight = _normalize_flight(item, query, self.name)
                        if flight:
                            results.append(flight)

        return results


# ── BingSearchSource Async Adapter ─────────────────────────────

class AsyncBingSearchSource(AsyncScraperBase):
    """Async adapter for BingSearchSource.

    Wraps the sync Bing search in a thread pool for non-blocking execution.
    """

    def __init__(self):
        from datasources.bing_search_source import BingSearchSource
        self._sync_scraper = BingSearchSource()
        self.name = "bing"

    def is_available(self) -> bool:
        return self._sync_scraper.is_available()

    def _sync_search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        return self._sync_scraper.search_flights(query)


# ── MultiAirlineScraper Async Adapter ──────────────────────────

class AsyncMultiSourceScraper(AsyncScraperBase):
    """Async adapter for MultiSourceScraper-based sources.

    Wraps the sync Playwright-based multi-source scraper in a thread pool.
    """

    def __init__(self, source_instance):
        self._sync_scraper = source_instance
        self.name = getattr(source_instance, "name", "multi_source")

    def is_available(self) -> bool:
        return self._sync_scraper.is_available()

    def _sync_search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        return self._sync_scraper.search_flights(query)
