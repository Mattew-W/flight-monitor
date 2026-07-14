"""
Flight Monitor - Amadeus Flight Data Source (No Browser!)
Uses Amadeus Self-Service API (free tier: 2000 calls/month).
Pure HTTP, no Playwright needed.
Sign up at: https://developers.amadeus.com/
"""
import logging
import time
import random
from datetime import datetime
from typing import List, Optional

from .base import BaseDataSource
from core.models import FlightPrice, SearchQuery

logger = logging.getLogger(__name__)

_amadeus_available = False
_amadeus_client = None

try:
    from amadeus import Client, ResponseError
    _amadeus_available = True
except ImportError:
    pass

# ── City → IATA code ────────────────────────────────────────────
CITY_IATA = {
    "北京": "PEK", "上海": "PVG", "广州": "CAN", "深圳": "SZX",
    "成都": "CTU", "杭州": "HGH", "武汉": "WUH", "西安": "XIY",
    "重庆": "CKG", "青岛": "TAO", "长沙": "CSX", "南京": "NKG",
    "厦门": "XMN", "昆明": "KMG", "大连": "DLC", "天津": "TSN",
    "三亚": "SYX", "海口": "HAK",
    "香港": "HKG", "台北": "TPE",
    "东京": "NRT", "大阪": "KIX", "首尔": "ICN",
    "新加坡": "SIN", "曼谷": "BKK",
    "迪拜": "DXB",
    "伦敦": "LHR", "巴黎": "CDG", "法兰克福": "FRA",
    "纽约": "JFK", "洛杉矶": "LAX", "旧金山": "SFO",
    "悉尼": "SYD",
}


class AmadeusSource(BaseDataSource):
    """Amadeus flight data via official API (free tier).

    No browser. Register at developers.amadeus.com for API key/secret.
    Set env vars: AMADEUS_KEY, AMADEUS_SECRET
    """

    name = "amadeus"

    def __init__(self):
        self._client = None

    def is_available(self) -> bool:
        return _amadeus_available

    def _get_client(self) -> Optional[Client]:
        if self._client is not None:
            return self._client
        import os
        key = os.environ.get("AMADEUS_KEY", "")
        secret = os.environ.get("AMADEUS_SECRET", "")
        if not key or not secret:
            logger.info("AmadeusSource: AMADEUS_KEY/SECRET not set, disabled")
            self._client = False
            return None
        try:
            self._client = Client(client_id=key, client_secret=secret)
        except Exception as e:
            logger.error(f"AmadeusSource: init failed: {e}")
            self._client = False
            return None
        return self._client

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        if not self.is_available():
            return []

        client = self._get_client()
        if not client:
            return []

        dep_code = CITY_IATA.get(query.departure, query.departure)
        arr_code = CITY_IATA.get(query.destination, query.destination)

        time.sleep(random.uniform(0.2, 1.0))

        try:
            resp = client.shopping.flight_offers_search.get(
                originLocationCode=dep_code,
                destinationLocationCode=arr_code,
                departureDate=query.departure_date,
                adults=1,
                max=20,
                currencyCode="CNY",
            )
            return self._parse_offers(resp.data, query)

        except ResponseError as e:
            logger.warning(f"AmadeusSource: API error: {e}")
            return []
        except Exception as e:
            logger.warning(f"AmadeusSource: search failed: {e}")
            return []

    def _parse_offers(self, offers: list, query: SearchQuery) -> List[FlightPrice]:
        results = []
        now = datetime.now().isoformat()
        for offer in offers:
            itinerary = offer.get("itineraries", [{}])[0]
            segments = itinerary.get("segments", [{}])
            first_seg = segments[0]
            last_seg = segments[-1]
            price_data = offer.get("price", {})
            total = float(price_data.get("grandTotal", 0))

            if total <= 0:
                continue

            airline = first_seg.get("carrierCode", "")
            flight_no = f"{airline}{first_seg.get('number', '')}"
            dep_time = first_seg.get("departure", {}).get("at", "")
            arr_time = last_seg.get("arrival", {}).get("at", "")

            if dep_time and "T" in dep_time:
                dep_time = dep_time.split("T")[-1][:5]
            if arr_time and "T" in arr_time:
                arr_time = arr_time.split("T")[-1][:5]

            stops = len(segments) - 1

            results.append(FlightPrice(
                query_id=query.id or 0,
                airline=airline,
                flight_no=flight_no,
                aircraft="",
                departure_time=dep_time,
                arrival_time=arr_time,
                departure_airport=query.departure,
                arrival_airport=query.destination,
                duration="",
                stops=stops,
                price=total,
                cabin_class=query.cabin_class or "economy",
                source=self.name,
                recorded_at=now,
                purchase_url="",
            ))

        logger.info(f"AmadeusSource: {len(results)} flights")
        return results[:30]
