"""
Flight Monitor - Async Scraper Base (S1 Framework)
===================================================
Provides a unified async interface for all data sources.

Problem solved:
  - browser_pool.py is fully async (AsyncBrowserPool)
  - multi_platform_scraper.py and airline_sniffer.py call it synchronously (BUG)
  - bing_search_source.py and multi_airline_scraper.py use sync_playwright independently

Solution:
  - AsyncScraperBase: wraps sync Playwright scrapers into async interface
  - SyncToAsyncBridge: runs sync scrapers in thread pool without blocking the event loop
  - All scrapers expose `async_search_flights()` for uniform async consumption

Usage:
    class MyScraper(AsyncScraperBase):
        def _sync_search(self, query):
            # existing sync code
            return prices

    # In async context:
    scraper = MyScraper()
    prices = await scraper.async_search_flights(query)
"""

import asyncio
import atexit
import inspect
import logging
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from core.models import FlightPrice, SearchQuery

logger = logging.getLogger(__name__)

# Shared thread pool for running sync scrapers from async context
# Avoids creating a new thread per call; bounded to prevent resource exhaustion
_sync_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="scraper-bridge")


def _shutdown_executor():
    """Gracefully shut down the global thread pool on process exit."""
    try:
        _sync_executor.shutdown(wait=False)
        logger.debug("Global sync_executor shut down cleanly")
    except Exception as e:
        logger.warning(f"Error shutting down sync_executor: {e}")


# Register shutdown hook so threads don't leak on process exit
atexit.register(_shutdown_executor)


class AsyncScraperBase:
    """Base class that wraps a synchronous scraper into an async interface.

    Subclasses implement `_sync_search_flights()` with their existing sync logic.
    The `async_search_flights()` method runs the sync code in a thread pool,
    making it safe to call from an async event loop without blocking.

    This is the recommended pattern for migrating sync scrapers to async:
    1. Inherit from AsyncScraperBase
    2. Move existing sync code into `_sync_search_flights()`
    3. Call `await scraper.async_search_flights(query)` from async code
    """

    name: str = "async_base"

    async def async_search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Async wrapper around the sync search implementation.

        Runs `_sync_search_flights()` in a thread pool to avoid blocking
        the event loop during Playwright/browser I/O.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _sync_executor,
            self._sync_search_flights,
            query,
        )

    def _sync_search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Override this with the actual sync search logic.

        By default, delegates to `search_flights()` if it exists and is sync.
        """
        if hasattr(self, 'search_flights') and callable(self.search_flights):
            if not inspect.iscoroutinefunction(self.search_flights):
                return self.search_flights(query)
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _sync_search_flights()"
        )

    def is_available(self) -> bool:
        return True


class AsyncBrowserScraperBase(AsyncScraperBase):
    """Base for scrapers that use the shared AsyncBrowserPool.

    Provides `async_search_flights()` that properly awaits the async pool.
    Subclasses implement `_async_search_impl()` with their browser logic.

    This replaces the broken pattern where sync code called
    `get_browser_pool()` without awaiting.
    """

    async def async_search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Run the async browser search directly (no thread pool needed)."""
        try:
            return await self._async_search_impl(query)
        except Exception as e:
            logger.error(f"[{self.name}] async search error: {e}")
            return []

    async def _async_search_impl(self, query: SearchQuery) -> List[FlightPrice]:
        """Override with async browser scraping logic."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _async_search_impl()"
        )


def run_sync_in_async(func):
    """Decorator: makes a sync function callable from async context.

    Usage:
        @run_sync_in_async
        def my_sync_scraper(query):
            return prices

        # In async code:
        prices = await my_sync_scraper(query)
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _sync_executor,
            functools.partial(func, *args, **kwargs),
        )
    return wrapper
