"""
Flight Monitor - Data Source Base Interface
"""
from abc import ABC, abstractmethod
from typing import List
from core.models import FlightPrice, SearchQuery

# ── S3-registered source registry ────────────────────────────────
_source_registry: dict[str, type['BaseDataSource']] = {}


def register_source(name: str):
    """Decorator to auto-register a data source class.
    
    Usage::
    
        @register_source("ctrip")
        class CtripDataSource(BaseDataSource):
            ...
    """
    def decorator(cls):
        cls.name = name
        _source_registry[name] = cls
        return cls
    return decorator


def get_source_class(name: str):
    """Return the registered data source class for *name* (or None)."""
    return _source_registry.get(name)


def list_sources():
    """Return a copy of the full registry."""
    return dict(_source_registry)


def create_source(name: str, **kwargs) -> 'BaseDataSource':
    """Create a data source instance by registered name."""
    cls = _source_registry.get(name)
    if cls is None:
        raise KeyError(f"Unknown data source: {name!r}")
    return cls(**kwargs)


class BaseDataSource(ABC):
    """Abstract base class for all flight data sources.

    Two valid implementation patterns:

    **Synchronous** (wraps automatically via ``_SyncToAsyncAdapter``)::

        @register_source("my_source")
        class MySource(BaseDataSource):
            def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
                ...

    **Asynchronous** (wrapped via ``_AsyncMethodAdapter``)::

        @register_source("my_source")
        class MyAsyncSource(BaseDataSource):
            async def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
                ...

    Use :func:`create_source` to instantiate a registered source by name.
    """

    name: str = "base"

    @abstractmethod
    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Search for flights matching the query.

        May be implemented as sync or async — the caller (``_wrap_source``)
        auto-detects and wraps accordingly.

        Args:
            query: Search query with departure, destination, date, etc.

        Returns:
            List of FlightPrice objects.
        """
        pass

    def is_available(self) -> bool:
        """Check if this data source is currently available."""
        return True
