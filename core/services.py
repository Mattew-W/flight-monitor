"""
Flight Monitor — Core Service Layer

Provides a unified API that core and api modules can call
without directly depending on datasources. Each service
internally delegates to the appropriate datasource or
schedules infrastructure.
"""
from __future__ import annotations

from typing import List, Dict, Optional, Any

from config import CITY_GROUPS

# Build once at import time (same as mock_source does).
_DOMESTIC_CITIES = set(CITY_GROUPS.get("中国大陆", []))


# ── Flight Schedule Service ──────────────────────────────────────────

class FlightScheduleService:
    """Wrapper around datasources.flight_schedules for flight details."""

    @staticmethod
    def lookup(flight_no: str) -> dict:
        """Look up a flight in the local schedules database."""
        from datasources.flight_schedules import lookup_flight_schedule
        return lookup_flight_schedule(flight_no) or {}

    @staticmethod
    def get_aircraft(flight_no: str) -> str:
        """Get aircraft type for a flight number."""
        from datasources.flight_schedules import get_aircraft_for_flight
        return get_aircraft_for_flight(flight_no) or ""

    @staticmethod
    def search_by_route(dep_city: str, arr_city: str) -> List[dict]:
        """Search local schedules for flights between two cities."""
        from datasources.flight_schedules import search_flights_by_route
        return search_flights_by_route(dep_city, arr_city)


# ── Route Service ────────────────────────────────────────────────────

class RouteService:
    """Route-level helpers (international detection, etc.)."""

    @staticmethod
    def is_international(departure: str, destination: str) -> bool:
        """Check whether a city pair is an international route."""
        dep_domestic = departure in _DOMESTIC_CITIES
        arr_domestic = destination in _DOMESTIC_CITIES
        return not (dep_domestic and arr_domestic)


# ── Bing Search Service ──────────────────────────────────────────────

class BingService:
    """Wrapper around datasources.bing_search_source for Bing queries."""

    def __init__(self):
        from datasources.bing_search_source import BingSearchSource
        self._source = BingSearchSource()

    def is_available(self) -> bool:
        return self._source.is_available()

    def search_flights(self, query: Any) -> List[Any]:
        """Search Bing for flight prices. `query` must be a SearchQuery."""
        return self._source.search_flights(query)

    def lookup_route(self, flight_no: str) -> dict:
        """Look up departure/arrival cities for a flight number via Bing."""
        return self._source.lookup_flight_route(flight_no) or {}

    def clear_negative_cache(self, flight_no: str) -> None:
        """Remove a flight number from the negative cache if stuck."""
        fn = flight_no.upper()
        if fn in self._source._route_negative_cache:
            del self._source._route_negative_cache[fn]
            self._source._save_route_cache()
