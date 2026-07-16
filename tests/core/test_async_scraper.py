"""
S2: Unit tests for core/async_scraper_base.py
Tests async wrapper behavior and thread pool execution.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch
from core.async_scraper_base import AsyncScraperBase, AsyncBrowserScraperBase
from core.models import SearchQuery, FlightPrice


class TestAsyncScraperBase:
    """Tests for the async scraper base class."""

    @pytest.mark.asyncio
    async def test_sync_scraper_wrapped_as_async(self):
        """A sync scraper should be callable via async interface."""

        class MyScraper(AsyncScraperBase):
            name = "test_scraper"

            def _sync_search_flights(self, query):
                return [FlightPrice(flight_no="CA123", price=500.0)]

        scraper = MyScraper()
        query = SearchQuery(departure="北京", destination="上海")
        results = await scraper.async_search_flights(query)

        assert len(results) == 1
        assert results[0].flight_no == "CA123"

    @pytest.mark.asyncio
    async def test_sync_scraper_with_existing_search_flights(self):
        """Scraper with sync search_flights() should work via async wrapper."""

        class LegacyScraper(AsyncScraperBase):
            name = "legacy"

            def search_flights(self, query):
                return [FlightPrice(flight_no="MU456", price=600.0)]

        scraper = LegacyScraper()
        query = SearchQuery(departure="北京", destination="上海")
        results = await scraper.async_search_flights(query)

        assert len(results) == 1
        assert results[0].price == 600.0

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """Exceptions in sync code should propagate properly."""

        class BrokenScraper(AsyncScraperBase):
            name = "broken"

            def _sync_search_flights(self, query):
                raise ValueError("Something went wrong")

        scraper = BrokenScraper()
        query = SearchQuery(departure="北京", destination="上海")

        with pytest.raises(ValueError, match="Something went wrong"):
            await scraper.async_search_flights(query)

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """Empty results should be returned as-is."""

        class EmptyScraper(AsyncScraperBase):
            name = "empty"

            def _sync_search_flights(self, query):
                return []

        scraper = EmptyScraper()
        query = SearchQuery(departure="北京", destination="上海")
        results = await scraper.async_search_flights(query)

        assert results == []


class TestAsyncBrowserScraperBase:
    """Tests for the async browser scraper base class."""

    @pytest.mark.asyncio
    async def test_async_search_implementation(self):
        """Async browser scraper should await its implementation."""

        class MyBrowserScraper(AsyncBrowserScraperBase):
            name = "browser_test"

            async def _async_search_impl(self, query):
                return [FlightPrice(flight_no="CZ789", price=700.0)]

        scraper = MyBrowserScraper()
        query = SearchQuery(departure="北京", destination="上海")
        results = await scraper.async_search_flights(query)

        assert len(results) == 1
        assert results[0].flight_no == "CZ789"

    @pytest.mark.asyncio
    async def test_async_exception_returns_empty(self):
        """Exceptions in async search should return empty list."""

        class BrokenAsyncScraper(AsyncBrowserScraperBase):
            name = "broken_async"

            async def _async_search_impl(self, query):
                raise RuntimeError("Browser crashed")

        scraper = BrokenAsyncScraper()
        query = SearchQuery(departure="北京", destination="上海")
        results = await scraper.async_search_flights(query)

        assert results == []
