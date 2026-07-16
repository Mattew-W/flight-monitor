"""
Flight Monitor - Data Source Chain (S4 Framework)
==================================================
Implements a priority-ordered chain of data sources with automatic fallback.

Architecture:
    SourceChain
      ├── sources: [SourceEntry(...)]  (ordered by priority)
      ├── search(query) → tries each source in order
      ├── on success: returns result, records success
      └── on failure: records failure, tries next source

    SourceEntry
      ├── source: BaseDataSource (or AsyncScraperBase)
      ├── priority: int (lower = higher priority)
      ├── circuit_breaker: CircuitBreaker instance
      └── is_async: bool (auto-detected)

Usage:
    chain = SourceChain()
    chain.add_source(CtripBrowserSource(), priority=1)
    chain.add_source(BingSearchSource(), priority=2)
    chain.add_source(MockDataSource(), priority=99)  # fallback

    prices = await chain.search(query)
    # Returns first successful result, or empty list if all fail
"""

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from core.models import FlightPrice, SearchQuery
from core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

logger = logging.getLogger(__name__)


@dataclass
class SourceEntry:
    """A single data source in the chain with metadata."""
    name: str
    source: Any  # BaseDataSource or AsyncScraperBase
    priority: int = 10
    circuit_breaker: Optional[CircuitBreaker] = None
    is_async: bool = False
    is_available: bool = True

    def __post_init__(self):
        # Auto-detect if source has async search
        if hasattr(self.source, 'async_search_flights'):
            self.is_async = inspect.iscoroutinefunction(self.source.async_search_flights)
        elif hasattr(self.source, 'search_flights'):
            self.is_async = inspect.iscoroutinefunction(self.source.search_flights)


class SourceChain:
    """Priority-ordered chain of data sources with automatic fallback.

    Sources are tried in priority order (lowest number first).
    If a source fails (exception or empty result), the next source is tried.
    Circuit breakers can temporarily skip unhealthy sources.
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._sources: List[SourceEntry] = []
        self._stats: Dict[str, Dict[str, int]] = {}

    def add_source(self, source, priority: int = 10,
                   circuit_breaker_config: Optional[CircuitBreakerConfig] = None) -> 'SourceChain':
        """Add a data source to the chain.

        Args:
            source: The data source instance (BaseDataSource or AsyncScraperBase)
            priority: Lower number = tried first (1 is highest priority)
            circuit_breaker_config: Optional circuit breaker settings
        """
        name = getattr(source, 'name', source.__class__.__name__)
        cb = None
        if circuit_breaker_config:
            cb = CircuitBreaker(name, circuit_breaker_config)

        entry = SourceEntry(
            name=name,
            source=source,
            priority=priority,
            circuit_breaker=cb,
        )
        self._sources.append(entry)
        self._sources.sort(key=lambda e: e.priority)
        self._stats[name] = {"success": 0, "failure": 0, "skipped": 0}
        logger.info(f"SourceChain[{self.name}]: added '{name}' (priority={priority})")
        return self

    async def search(self, query: SearchQuery) -> List[FlightPrice]:
        """Search for flights using the source chain.

        Tries each source in priority order until one returns results.
        Failed sources are skipped and their circuit breakers updated.
        """
        if not self._sources:
            logger.warning(f"SourceChain[{self.name}]: no sources configured")
            return []

        for entry in self._sources:
            # Check circuit breaker
            if entry.circuit_breaker and not entry.circuit_breaker.can_execute():
                logger.debug(f"SourceChain[{self.name}]: '{entry.name}' circuit open, skipping")
                self._stats[entry.name]["skipped"] += 1
                continue

            # Check availability
            if hasattr(entry.source, 'is_available') and not entry.source.is_available():
                logger.debug(f"SourceChain[{self.name}]: '{entry.name}' not available, skipping")
                self._stats[entry.name]["skipped"] += 1
                continue

            try:
                prices = await self._execute_source(entry, query)
                if prices:
                    # Success: record and return
                    self._stats[entry.name]["success"] += 1
                    if entry.circuit_breaker:
                        entry.circuit_breaker.record_success()
                    logger.info(
                        f"SourceChain[{self.name}]: '{entry.name}' returned "
                        f"{len(prices)} results"
                    )
                    return prices
                else:
                    # Empty result: not a failure, but try next source
                    logger.debug(
                        f"SourceChain[{self.name}]: '{entry.name}' returned empty, "
                        f"trying next"
                    )
            except Exception as e:
                # Failure: record and try next source
                self._stats[entry.name]["failure"] += 1
                if entry.circuit_breaker:
                    entry.circuit_breaker.record_failure()
                logger.warning(
                    f"SourceChain[{self.name}]: '{entry.name}' failed: {e}, "
                    f"trying next"
                )

        logger.warning(f"SourceChain[{self.name}]: all sources exhausted, no results")
        return []

    async def _execute_source(self, entry: SourceEntry, query: SearchQuery) -> List[FlightPrice]:
        """Execute a single source (handles both sync and async)."""
        if entry.is_async:
            if hasattr(entry.source, 'async_search_flights'):
                return await entry.source.async_search_flights(query)
            elif hasattr(entry.source, 'search_flights'):
                return await entry.source.search_flights(query)
        else:
            # Run sync source in thread pool
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,  # default executor
                entry.source.search_flights,
                query,
            )

    async def search_all(self, query: SearchQuery) -> List[FlightPrice]:
        """Search all available sources and aggregate results.

        Unlike `search()` which returns on first success, this tries every
        source and aggregates all results. Useful for one-shot searches where
        maximum coverage is desired.
        """
        if not self._sources:
            logger.warning(f"SourceChain[{self.name}]: no sources configured")
            return []

        all_prices: List[FlightPrice] = []

        for entry in self._sources:
            # Check circuit breaker
            if entry.circuit_breaker and not entry.circuit_breaker.can_execute():
                logger.debug(f"SourceChain[{self.name}]: '{entry.name}' circuit open, skipping")
                self._stats[entry.name]["skipped"] += 1
                continue

            # Check availability
            if hasattr(entry.source, 'is_available') and not entry.source.is_available():
                logger.debug(f"SourceChain[{self.name}]: '{entry.name}' not available, skipping")
                self._stats[entry.name]["skipped"] += 1
                continue

            try:
                prices = await self._execute_source(entry, query)
                if prices:
                    self._stats[entry.name]["success"] += 1
                    if entry.circuit_breaker:
                        entry.circuit_breaker.record_success()
                    all_prices.extend(prices)
                    logger.info(
                        f"SourceChain[{self.name}]: '{entry.name}' returned "
                        f"{len(prices)} results (aggregated)"
                    )
                else:
                    logger.debug(
                        f"SourceChain[{self.name}]: '{entry.name}' returned empty"
                    )
            except Exception as e:
                self._stats[entry.name]["failure"] += 1
                if entry.circuit_breaker:
                    entry.circuit_breaker.record_failure()
                logger.warning(
                    f"SourceChain[{self.name}]: '{entry.name}' failed: {e}"
                )

        return all_prices

    def get_circuit_breaker_info(self) -> Dict[str, dict]:
        """Return circuit breaker state for each source."""
        info = {}
        for entry in self._sources:
            if entry.circuit_breaker:
                info[entry.name] = entry.circuit_breaker.get_info()
        return info

    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """Return success/failure/skip statistics for each source."""
        return dict(self._stats)

    def get_source_names(self) -> List[str]:
        """Return ordered list of source names in the chain."""
        return [e.name for e in self._sources]

    def __len__(self) -> int:
        return len(self._sources)

    def __repr__(self) -> str:
        names = ", ".join(f"{e.name}(p{e.priority})" for e in self._sources)
        return f"SourceChain({names})"
