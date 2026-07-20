"""
Universal Airline API Sniffer — 通用航司数据嗅探器

原理: 用 Playwright 访问航司搜索页，拦截所有 JSON 响应，
     自动识别包含航班数据的响应并提取。

优势:
  - 不需要预先知道 API endpoint
  - 一次嗅探就能发现所有数据
  - 对任何航司通用

支持的航司 (配置即可, 无需修改代码):
  - airchina: 国航 m.airchina.com.cn
  - csair: 南航 m.csair.com
  - ceair: 东航 m.ceair.com
  - 可扩展...
"""
import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import quote

from core.models import FlightPrice, SearchQuery
from datasources.base import BaseDataSource

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from core.browser_pool import get_browser_pool


# ══════════════════════════════════════════════════════════════
#  Per-airline configuration
#  Add new airlines by adding entries here.
# ══════════════════════════════════════════════════════════════

AIRLINE_CONFIGS = {
    "airchina": {
        "name": "中国国航",
        "search_url": (
            "https://m.airchina.com.cn/#/flightSearch?"
            "tripType=OW&depCity={dep}&arrCity={arr}&depDate={date}"
            "&adtCount=1&chdCount=0&infCount=0"
        ),
        "city_map": {
            "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
            "成都": "CTU", "杭州": "HGH", "南京": "NKG", "武汉": "WUH",
            "重庆": "CKG", "厦门": "XMN", "青岛": "TAO", "西安": "XIY",
            "昆明": "KMG", "大连": "DLC", "天津": "TSN",
        },
    },
    "csair": {
        "name": "南方航空",
        "search_url": (
            "https://m.csair.com/#/flight?"
            "tripType=0&depCity={dep}&arrCity={arr}&depDate={date}&adt=1"
        ),
        "city_map": {
            "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
            "成都": "CTU", "杭州": "HGH", "南京": "NKG", "武汉": "WUH",
            "重庆": "CKG", "厦门": "XMN", "昆明": "KMG",
        },
    },
    "ceair": {
        "name": "东方航空",
        "search_url": (
            "https://m.ceair.com/#/flight?"
            "type=OW&depcd={dep}&arrcd={arr}&depdt={date}&adt=1"
        ),
        "city_map": {
            "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
            "成都": "CTU", "杭州": "HGH", "南京": "NKG", "武汉": "WUH",
            "重庆": "CKG", "厦门": "XMN", "西安": "XIY",
        },
    },
}


# ══════════════════════════════════════════════════════════════
#  Flight data auto-detection
# ══════════════════════════════════════════════════════════════

FLIGHT_FIELD_PATTERNS = {
    "flight_no": [
        r'^[A-Z]{2}\d{2,4}$',           # exact: CA1234
        r'^[A-Z0-9]{3,8}$',              # lenient
    ],
    "price_fields": [
        "price", "lowestPrice", "salePrice", "ticketPrice",
        "adultPrice", "totalPrice", "baseFare", "totalFare",
        "minPrice", "displayPrice", "fare", "amount",
    ],
    "airline_fields": [
        "airlineName", "carrier", "carrierName", "airlineCode",
        "airCompany", "flightCompany",
    ],
    "time_fields": [
        "departTime", "departureTime", "deptTime",
        "arriveTime", "arrivalTime", "arrTime",
    ],
}


def _is_flight_record(obj: dict) -> bool:
    """Heuristic: does this dict look like a flight record?"""
    if not isinstance(obj, dict):
        return False
    # Must have something that looks like a flight number
    for key, val in obj.items():
        if isinstance(val, str) and re.match(r'^[A-Z]{2}\d{2,4}$', val):
            return True
    return False


def _find_flight_list(data, depth: int = 0) -> Optional[List[dict]]:
    """Recursively find a list of flight-like objects in arbitrary JSON."""
    if depth > 10:
        return None
    
    if isinstance(data, list):
        if len(data) > 0 and _is_flight_record(data[0]):
            return data
        # Check first few items
        for item in data[:3]:
            result = _find_flight_list(item, depth + 1)
            if result:
                return result
    elif isinstance(data, dict):
        for key in ["flightList", "flights", "data", "result", "itineraryList",
                     "flightInfoList", "scheduleList", "availList", "segments"]:
            if key in data:
                result = _find_flight_list(data[key], depth + 1)
                if result:
                    return result
        # Check ALL values
        for val in data.values():
            result = _find_flight_list(val, depth + 1)
            if result:
                return result
    
    return None


def _extract_price(item: dict) -> float:
    """Extract price from a flight-like dict, trying all known price field names."""
    for field in FLIGHT_FIELD_PATTERNS["price_fields"]:
        val = item.get(field)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    # Try nested price objects
    for sub_key in ["priceInfo", "price", "fareInfo"]:
        sub = item.get(sub_key)
        if isinstance(sub, dict):
            return _extract_price(sub)
    return 0


def _extract_field(item: dict, candidates: List[str]) -> str:
    """Try multiple field names, return first non-empty value."""
    for key in candidates:
        val = item.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _normalize_flight(item: dict, query: SearchQuery, source: str) -> Optional[FlightPrice]:
    """Convert arbitrary flight-like dict to FlightPrice."""
    now = datetime.now().isoformat()
    
    # Find flight number
    fn = ""
    for key, val in item.items():
        if isinstance(val, str) and re.match(r'^[A-Z]{2}\d{2,4}$', val):
            fn = val
            break
    if not fn:
        fn = _extract_field(item, ["flightNo", "flightNumber", "fltNo", "flightCode"])
    if not fn:
        return None
    
    price = _extract_price(item)
    if price <= 0:
        return None
        try:
            stops = int(_extract_field(item, ["stopCount", "stops", "transferCount"]) or 0)
        except (ValueError, TypeError):
            stops = 0
        return FlightPrice(
            query_id=query.id or 0,
            airline=_extract_field(item, FLIGHT_FIELD_PATTERNS["airline_fields"]) or fn[:2],
            flight_no=fn,
            aircraft=_extract_field(item, ["aircraftType", "craftType", "planeType", "equipment"]),
            departure_time=_extract_field(item, FLIGHT_FIELD_PATTERNS["time_fields"][:3]),
            arrival_time=_extract_field(item, FLIGHT_FIELD_PATTERNS["time_fields"][3:]),
            departure_airport=_extract_field(item, ["depAirport", "depPort", "departureAirport", "fromAirport"]),
            arrival_airport=_extract_field(item, ["arrAirport", "arrPort", "arrivalAirport", "toAirport"]),
            duration=_extract_field(item, ["duration", "flyTime", "travelTime"]),
            stops=stops,
            price=price,
        cabin_class=query.cabin_class,
        source=source,
        recorded_at=now,
        purchase_url="",
    )


# ══════════════════════════════════════════════════════════════
#  Main scraper class
# ══════════════════════════════════════════════════════════════

class AirlineSnifferSource(BaseDataSource):
    """Universal airline data sniffer - works with any configured airline."""
    
    def __init__(self, airline_key: str):
        cfg = AIRLINE_CONFIGS.get(airline_key)
        if not cfg:
            raise ValueError(f"Unknown airline: {airline_key}. Available: {list(AIRLINE_CONFIGS.keys())}")
        self._key = airline_key
        self._cfg = cfg
        self.name = f"{airline_key}_sniffer"
    
    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT
    
    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Sync path is NOT supported — browser pool is async-only.
        Use ``AsyncAirlineSnifferSource`` (from async_adapters) instead."""
        raise NotImplementedError(
            f"AirlineSnifferSource({self._key}) does not support sync calls. "
            f"Use AsyncAirlineSnifferSource from datasources.async_adapters."
        )


# ══════════════════════════════════════════════════════════════
#  Factory
# ══════════════════════════════════════════════════════════════

def create_all_sources() -> Dict[str, BaseDataSource]:
    """Create all configured airline sniffer sources."""
    sources = {}
    for key in AIRLINE_CONFIGS:
        try:
            sources[key] = AirlineSnifferSource(key)
        except Exception as e:
            logger.warning(f"Failed to create {key}: {e}")
    return sources
