"""
Flight Monitor - Minimal Skyscanner Client
Pure HTTP client (no browser) for Skyscanner's Android API.
Uses curl_cffi for TLS fingerprint emulation.
"""
import json
import logging
import time
import random
import uuid
from typing import List, Optional, Dict
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

try:
    from curl_cffi import requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    HAS_CURL_CFFI = False

# ── API endpoints ───────────────────────────────────────────────
SKYSCANNER_BASE = "https://www.skyscanner.net"
API_AUTOCOMPLETE = "https://www.skyscanner.net/g/autosuggest-flights/"

# Headers to emulate Android app
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": SKYSCANNER_BASE,
    "Referer": f"{SKYSCANNER_BASE}/",
}

# ── City → IATA + entity ID mapping ─────────────────────────────
_CITY_MAP: Dict[str, tuple] = {
    # (iata, entity_id)
    "北京":   ("BJS", "27539733"), "上海": ("SHA", "27539791"),
    "广州":   ("CAN", "27539924"), "深圳": ("SZX", "27539925"),
    "成都":   ("CTU", "27539734"), "杭州": ("HGH", "27539787"),
    "武汉":   ("WUH", "27539927"), "西安": ("XIY", "27539928"),
    "重庆":   ("CKG", "27539786"), "青岛": ("TAO", "27539930"),
    "长沙":   ("CSX", "27539931"), "南京": ("NKG", "27539932"),
    "厦门":   ("XMN", "27539933"), "昆明": ("KMG", "27539934"),
    "大连":   ("DLC", "27539935"), "天津": ("TSN", "27539936"),
    "三亚":   ("SYX", "27539937"), "海口": ("HAK", "27539938"),
    "哈尔滨": ("HRB", "27539939"), "沈阳": ("SHE", "27539940"),
    "香港":   ("HKG", "27539941"), "台北": ("TPE", "27539942"),
    "东京":   ("TYO", "27539863"), "大阪": ("OSA", "27539864"),
    "首尔":   ("SEL", "27539865"),
    "新加坡": ("SIN", "27539866"), "曼谷": ("BKK", "27539867"),
    "迪拜":   ("DXB", "27539868"),
    "伦敦":   ("LON", "27539869"), "巴黎": ("PAR", "27539870"),
    "纽约":   ("NYC", "27539871"), "洛杉矶": ("LAX", "27539872"),
    "悉尼":   ("SYD", "27539873"), "墨尔本": ("MEL", "27539874"),
}


def _search_airport(city: str) -> Optional[str]:
    """Get Skyscanner entity ID for a city."""
    if city in _CITY_MAP:
        return _CITY_MAP[city][1]

    # Try autocomplete API
    params = {
        "q": city,
        "locale": "zh-CN",
        "market": "CN",
        "currency": "CNY",
    }
    try:
        resp = requests.get(
            f"{API_AUTOCOMPLETE}{city}",
            params={
                "locale": "zh-CN",
                "market": "CN",
                "currency": "CNY",
            },
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            places = data.get("PlaceSummaries", data.get("places", []))
            if places:
                pid = places[0].get("PlaceId", places[0].get("entityId", ""))
                if pid:
                    _CITY_MAP[city] = (_CITY_MAP.get(city, (city, ""))[0], pid)
                    return pid
    except Exception as e:
        logger.debug(f"Skyscanner autocomplete failed for {city}: {e}")

    return None


def search_flights_skyscanner(dep: str, arr: str, date: str,
                              cabin: str = "economy",
                              currency: str = "CNY",
                              market: str = "CN",
                              locale: str = "zh-CN",
                              adults: int = 1) -> List[dict]:
    """Search Skyscanner for flights using the browse API.

    Returns list of dicts with keys: airline, flight_no, price, departure_time,
    arrival_time, duration_min, stops.

    No browser needed — uses Skyscanner's public browse API.
    """
    dep_id = _search_airport(dep)
    arr_id = _search_airport(arr)
    if not dep_id or not arr_id:
        return []

    # Skyscanner browse API (no auth needed)
    # POST to the graphql-like browse endpoint
    browse_url = f"{SKYSCANNER_BASE}/g/chiron/api/v1/flights/browse/browseroutes/v1.0"
    browse_url_alt = f"{SKYSCANNER_BASE}/g/chiron/api/v1/flights/browsequotes/v1.0"

    payload = {
        "market": market,
        "locale": locale,
        "currency": currency,
        "queryLegs": [
            {
                "originPlace": {"queryPlace": {"id": dep_id}},
                "destinationPlace": {"queryPlace": {"id": arr_id}},
                "date": {"year": int(date[:4]), "month": int(date[5:7]), "day": int(date[8:10])},
            }
        ],
        "adults": adults,
        "cabinClass": f"CABIN_CLASS_{cabin.upper()}",
    }

    try:
        resp = requests.post(
            browse_url,
            json=payload,
            headers={**_HEADERS, "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            # Try alternate endpoint
            resp = requests.post(
                browse_url_alt,
                json=payload,
                headers={**_HEADERS, "Content-Type": "application/json"},
                timeout=15,
            )

        if resp.status_code == 200:
            return _parse_browse_response(resp.json())
        else:
            logger.warning(f"Skyscanner API returned {resp.status_code}")
            return []
    except Exception as e:
        logger.warning(f"Skyscanner search failed: {e}")
        return []


def _parse_browse_response(data: dict) -> List[dict]:
    """Parse Skyscanner browse API response."""
    results = []

    # Navigate response structure
    quotes = []
    carriers = {}
    places = {}
    legs = {}

    if "Quotes" in data:
        quotes = data["Quotes"]
    if "Carriers" in data:
        carriers = {c["CarrierId"]: c for c in data["Carriers"]}
    if "Places" in data:
        places = {p["PlaceId"]: p for p in data["Places"]}
    if "Legs" in data:
        legs = {l["LegId"]: l for l in data["Legs"]}

    # Also try nested format
    if not quotes:
        for container in ("data", "content", "results", "itineraries"):
            inner = data.get(container, {})
            if isinstance(inner, dict):
                quotes = inner.get("Quotes", inner.get("quotes", []))
                if quotes:
                    carriers = inner.get("Carriers", inner.get("carriers", {}))
                    places = inner.get("Places", inner.get("places", {}))
                    legs = inner.get("Legs", inner.get("legs", {}))
                    break

    for quote in quotes:
        price = quote.get("MinPrice", quote.get("Price", 0))
        if price <= 0:
            continue

        outbound_leg_id = quote.get("OutboundLeg", {}).get("LegId", "")
        leg = legs.get(outbound_leg_id, {})

        # Get carrier
        carrier_ids = leg.get("CarrierIds", quote.get("OutboundLeg", {}).get("CarrierIds", []))
        airline = ""
        if carrier_ids and carriers:
            cid = carrier_ids[0] if isinstance(carrier_ids, list) else carrier_ids
            airline = carriers.get(cid, {}).get("Name", "")

        # Get times
        departure_time = leg.get("Departure", "")
        arrival_time = leg.get("Arrival", "")
        duration_min = leg.get("Duration", 0)

        # Get flight numbers
        flight_numbers = leg.get("FlightNumbers", [])
        flight_no = flight_numbers[0].get("FlightNumber", "") if flight_numbers else ""

        if not airline:
            continue

        results.append({
            "airline": airline,
            "flight_no": flight_no,
            "price": price,
            "departure_time": departure_time,
            "arrival_time": arrival_time,
            "duration_min": duration_min,
            "stops": leg.get("Stops", quote.get("OutboundLeg", {}).get("Stops", 0)),
        })

    results.sort(key=lambda x: x["price"])
    return results[:30]


# ── Quick test ──────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing Skyscanner search...")
    t0 = time.time()
    results = search_flights_skyscanner("北京", "上海", "2026-08-15")
    elapsed = time.time() - t0
    print(f"Found {len(results)} flights in {elapsed:.1f}s")
    for r in results[:5]:
        print(f"  {r['airline']} {r['flight_no']} ¥{r['price']} "
              f"{r['departure_time']}-{r['arrival_time']}")
