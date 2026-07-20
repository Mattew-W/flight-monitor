"""
Flight Monitor - Ctrip Data Source
Uses Ctrip's public lowest-price API to fetch flight data.
Falls back gracefully if the API is unavailable or blocked.
"""
import json
import logging
from typing import List, Optional
from .base import BaseDataSource, register_source
from core.models import FlightPrice, SearchQuery
from config import CITY_CODES, CTRIP_API_URL, CTRIP_HEADERS

logger = logging.getLogger(__name__)


@register_source("ctrip")
class CtripDataSource(BaseDataSource):
    """Ctrip (携程) flight data source using public API."""

    name = "ctrip"

    def __init__(self):
        try:
            import requests
            self._requests = requests
        except ImportError:
            logger.warning("requests not installed, CtripDataSource disabled")
            self._requests = None

    def is_available(self) -> bool:
        return self._requests is not None

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Search flights via Ctrip API.

        Uses the public lowest-price endpoint. Note that Ctrip may rate-limit
        or block automated requests; this source is best-effort.
        """
        if not self.is_available():
            return []

        dep_code = CITY_CODES.get(query.departure)
        arr_code = CITY_CODES.get(query.destination)
        if not dep_code or not arr_code:
            logger.warning(f"City code not found for {query.departure} -> {query.destination}")
            return []

        try:
            # Try the lowest price API with departure date
            url = (f"{CTRIP_API_URL}?flightWay=Oneway&dcity={dep_code}&acity={arr_code}"
                   f"&direct=true&ddate={query.departure_date}")
            resp = self._requests.get(url, headers=CTRIP_HEADERS, timeout=10)

            if resp.status_code in (403, 432):
                logger.warning(
                    f"Ctrip blocked request (status={resp.status_code}) "
                    f"for {query.departure}->{query.destination}: possible anti-bot"
                )
                return []

            resp.raise_for_status()
            data = resp.json()

            return self._parse_ctrip_response(data, query)
        except Exception as e:
            logger.warning(f"Ctrip API request failed: {e}")
            return []

    def _parse_ctrip_response(self, data: dict, query: SearchQuery) -> List[FlightPrice]:
        """Parse Ctrip API response into FlightPrice objects."""
        flights: List[FlightPrice] = []
        from datetime import datetime
        now = datetime.now().isoformat()

        try:
            # Ctrip lowest price API response structure
            one_way = data.get("data", {}).get("oneWay", {})
            flight_list = one_way.get("flightList", [])

            for flight in flight_list[:15]:
                price_list = flight.get("priceList", [])
                if not price_list:
                    continue

                min_price_item = min(price_list, key=lambda p: p.get("price", 999999))
                price = min_price_item.get("price", 0)

                legs = flight.get("legs", [])
                if not legs:
                    continue
                leg = legs[0]

                airline = leg.get("airlineName", "")
                flight_no = leg.get("flightNo", "")
                aircraft = leg.get("craftType", "")
                dep_time = leg.get("departureTime", "")
                arr_time = leg.get("arrivalTime", "")
                dep_airport = leg.get("departureAirportName", "")
                arr_airport = leg.get("arrivalAirportName", "")
                duration = leg.get("duration", "")
                stops = len(legs) - 1

                flights.append(FlightPrice(
                    query_id=query.id or 0,
                    airline=airline,
                    flight_no=flight_no,
                    aircraft=aircraft,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    departure_airport=dep_airport,
                    arrival_airport=arr_airport,
                    duration=duration,
                    stops=stops,
                    price=float(price),
                    cabin_class=query.cabin_class,
                    source=self.name,
                    recorded_at=now,
                ))
        except (KeyError, TypeError) as e:
            logger.warning(f"Failed to parse Ctrip response: {e}")

        flights.sort(key=lambda f: f.price)
        return flights
