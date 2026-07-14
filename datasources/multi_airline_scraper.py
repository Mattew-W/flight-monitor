"""
Multi-Source Airline Scraper — 多航司官网 + OTA 统一爬虫

基于 Playwright headless 浏览器，统一拦截各航司/平台 Mobile API。
复用现有的 CtripBrowserSource 浏览器实例，避免重复启动。

数据源优先级:
  1. 携程 Ctrip H5 (已有，getLowestPriceCalendar)
  2. Trip.com 国际站 (同公司，国际航线价格更全)
  3. 天巡 Skyscanner 国内版 (tianxun.com)
  4. 国航/南航/东航官网 (逐步添加)

所有爬虫共享一个 Playwright 浏览器，顺序切换 Tab，不影响性能。
"""
import json
import logging
import re
import time
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import quote, urlencode

from core.models import FlightPrice, SearchQuery
from datasources.base import BaseDataSource

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# ══════════════════════════════════════════════════════════════
#  Base: Multi-source Playwright scraper
# ══════════════════════════════════════════════════════════════

class MultiSourceScraper(BaseDataSource):
    """Unified multi-airline scraper using a shared Playwright browser.
    
    Subclasses only need to implement `_build_url()` and `_parse_response()`.
    Browser management is handled by the base class.
    """
    name = "multi_source"
    
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
    
    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT
    
    def _ensure_browser(self):
        """Lazy-init the Playwright browser (lightweight headless)."""
        if self._browser:
            return
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=["--headless=new", "--no-sandbox", "--disable-gpu",
                  "--disable-dev-shm-usage", "--window-size=375,812"],
        )
        self._context = self._browser.new_context(
            viewport={"width": 375, "height": 812},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/16.0 Mobile/15E148 Safari/604.1"
            ),
            locale="zh-CN",
        )
        logger.info(f"MultiSourceScraper: Browser ready")
    
    def close(self):
        """Clean up browser resources."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
    
    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        return []
    
    def _intercept_json(self, page: Page, url_pattern: str, timeout_ms: int = 15000) -> Optional[dict]:
        """Intercept a JSON API response matching a URL pattern."""
        result = {"data": None}
        
        def on_response(response):
            if url_pattern in response.url and response.status == 200:
                try:
                    result["data"] = response.json()
                except Exception:
                    pass
        
        page.on("response", on_response)
        page.wait_for_timeout(timeout_ms)
        page.remove_listener("response", on_response)
        return result["data"]
    
    def interceptor(self, page: Page, patterns: List[str], timeout_ms: int = 15000) -> List[dict]:
        """Intercept multiple JSON API responses matching any of the patterns."""
        captured = []
        
        def on_response(response):
            for p in patterns:
                if p in response.url and response.status == 200:
                    try:
                        captured.append(response.json())
                    except Exception:
                        pass
                    break
        
        page.on("response", on_response)
        page.wait_for_timeout(timeout_ms)
        page.remove_listener("response", on_response)
        return captured
# ══════════════════════════════════════════════════════════════
#  Source 1: Trip.com International
# ══════════════════════════════════════════════════════════════

class TripComSource(BaseDataSource):
    """Trip.com (携程国际站) flight data source.
    
    Same company as Ctrip but different API endpoints and pricing.
    Better coverage for international routes.
    Uses the shared Playwright browser from MultiSourceScraper.
    """
    name = "tripcom_scraper"
    
    # City IATA -> Trip.com search codes
    CITY_MAP = {
        "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
        "成都": "CTU", "杭州": "HGH", "南京": "NKG", "武汉": "WUH",
        "重庆": "CKG", "厦门": "XMN", "青岛": "TAO", "西安": "XIY",
        "昆明": "KMG", "大连": "DLC", "天津": "TSN", "三亚": "SYX",
        "香港": "HKG", "台北": "TPE", "澳门": "MFM",
        "东京": "TYO", "大阪": "OSA", "首尔": "SEL", "新加坡": "SIN",
        "曼谷": "BKK", "吉隆坡": "KUL", "伦敦": "LON", "巴黎": "PAR",
        "纽约": "NYC", "洛杉矶": "LAX", "悉尼": "SYD",
    }
    
    def __init__(self, shared_scraper: MultiSourceScraper = None):
        self._shared = shared_scraper or MultiSourceScraper()
    
    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT
    
    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Search Trip.com mobile site for flights."""
        dep_code = self.CITY_MAP.get(query.departure, "")
        arr_code = self.CITY_MAP.get(query.destination, "")
        if not dep_code or not arr_code:
            return []
        
        self._shared._ensure_browser()
        page = self._shared._context.new_page()
        results = []
        
        try:
            url = (
                f"https://www.trip.com/flights/{dep_code}-{arr_code}/"
                f"?ddate={query.departure_date}&dcity={dep_code}&acity={arr_code}"
                f"&class=economy&quantity=1&searchid=&multimodel=false"
            )
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            # Try multiple API response patterns
            captured = []
            def on_response(response):
                url_lower = response.url.lower()
                if any(k in url_lower for k in ["flightlist", "searchflight", "getflight",
                                                  "onewaylist", "lowestprice"]):
                    if response.status == 200:
                        try:
                            captured.append(response.json())
                        except Exception:
                            pass
            
            page.on("response", on_response)
            page.wait_for_timeout(8000)
            page.remove_listener("response", on_response)
            
            # Parse captured data
            for data in captured:
                flights = self._extract_flights(data, query)
                results.extend(flights)
            
            if results:
                logger.info(f"Trip.com: {len(results)} flights for "
                           f"{query.departure}->{query.destination}")
        except Exception as e:
            logger.debug(f"Trip.com error: {e}")
        finally:
            page.close()
        
        return results
    
    def _extract_flights(self, data: dict, query: SearchQuery) -> List[FlightPrice]:
        """Extract FlightPrice objects from Trip.com API response."""
        results = []
        now = datetime.now().isoformat()
        
        # Try common JSON paths
        items = (
            data.get("flightItineraryList") or
            data.get("flightList") or
            data.get("itineraryList") or
            data.get("data", {}).get("flightList") or
            []
        )
        if isinstance(data, list):
            items = data
        
        seen = set()
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            
            flight_no = item.get("flightNo") or item.get("flightNumber", "")
            if not flight_no or flight_no in seen:
                continue
            seen.add(flight_no)
            
            price_info = item.get("priceInfo") or item.get("price", {})
            price = (
                price_info.get("totalPrice") or
                price_info.get("salePrice") or
                item.get("lowestPrice") or
                item.get("price") or
                0
            )
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            
            if price <= 0:
                continue
            
            segments = item.get("segments") or item.get("flightSegments", [])
            first_seg = segments[0] if segments else item
            
            results.append(FlightPrice(
                query_id=query.id or 0,
                airline=item.get("airlineName") or first_seg.get("airlineName", "未知"),
                flight_no=flight_no,
                aircraft=item.get("craftType") or first_seg.get("craftType", ""),
                departure_time=first_seg.get("departureTime", ""),
                arrival_time=first_seg.get("arrivalTime", ""),
                departure_airport=first_seg.get("departureAirport", query.departure),
                arrival_airport=first_seg.get("arrivalAirport", query.destination),
                duration=first_seg.get("duration", ""),
                stops=item.get("stopCount", 0),
                price=price,
                cabin_class=query.cabin_class,
                source=self.name,
                recorded_at=now,
                purchase_url=(
                    f"https://www.trip.com/flights/{query.departure}-{query.destination}/"
                    f"?ddate={query.departure_date}"
                ),
            ))
        
        return results


# ══════════════════════════════════════════════════════════════
#  Source 2: Domestic airline mobile sites (generic interceptor)
# ══════════════════════════════════════════════════════════════

class AirlineOfficialSource(BaseDataSource):
    """Generic domestic airline official site scraper.
    
    Visits the mobile search page and intercepts flight data APIs.
    Configurable per airline via AIRLINE_CONFIG.
    """
    name = "airline_official"
    
    AIRLINE_CONFIG = {
        "airchina": {
            "search_url": (
                "https://m.airchina.com.cn/flightsearch?"
                "tripType=OW&depCity={dep}&arrCity={arr}&depDate={date}"
                "&adultCount=1&childCount=0&infantCount=0&cabin=Y"
            ),
            "api_patterns": ["flight/search", "queryFlight", "getFlight"],
            "field_map": {
                "flightNo": ["flightNo", "flightNumber"],
                "airline": ["airlineName", "carrier"],
                "price": ["lowestPrice", "salePrice", "price"],
                "depTime": ["departTime", "departureTime"],
                "arrTime": ["arriveTime", "arrivalTime"],
            },
        },
        "csair": {
            "search_url": (
                "https://m.csair.com/flight/search?"
                "tripType=0&fromCity={dep}&toCity={arr}&fromDate={date}"
                "&adultNum=1&childNum=0&infantNum=0"
            ),
            "api_patterns": ["queryFlight", "searchFlight", "getFlightList"],
            "field_map": {
                "flightNo": ["flightNo", "flightNumber"],
                "airline": ["airlineName", "carrierName"],
                "price": ["lowestPrice", "ticketPrice", "price"],
                "depTime": ["departTime", "departureTime"],
                "arrTime": ["arriveTime", "arrivalTime"],
            },
        },
        "ceair": {
            "search_url": (
                "https://m.ceair.com/flight/search?"
                "tripType=OW&depCd={dep}&arrCd={arr}&depDt={date}"
                "&adt=1&chd=0&inf=0"
            ),
            "api_patterns": ["flight/search", "queryAv", "getAvail"],
            "field_map": {
                "flightNo": ["flightNo", "flightNumber"],
                "airline": ["airlineName", "carrier"],
                "price": ["lowestPrice", "price", "adultPrice"],
                "depTime": ["departTime", "deptTime"],
                "arrTime": ["arriveTime", "arrTime"],
            },
        },
    }
    
    def __init__(self, airline_key: str, shared_scraper: MultiSourceScraper = None):
        self._shared = shared_scraper or MultiSourceScraper()
        self._config = self.AIRLINE_CONFIG.get(airline_key)
        self._airline_key = airline_key
        if not self._config:
            raise ValueError(f"Unknown airline: {airline_key}")
    
    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT and bool(self._config)
    
    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Scrape the airline's mobile search page."""
        from config import CITY_CODES
        
        dep_code = CITY_CODES.get(query.departure, query.departure)
        arr_code = CITY_CODES.get(query.destination, query.destination)
        
        self._shared._ensure_browser()
        page = self._shared._context.new_page()
        results = []
        
        try:
            url = self._config["search_url"].format(
                dep=dep_code, arr=arr_code, date=query.departure_date
            )
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            captured = self._shared.interceptor(
                page, self._config["api_patterns"], timeout_ms=12000
            )
            
            for data in captured:
                flights = self._parse_response(data, query)
                results.extend(flights)
            
            if results:
                logger.info(f"[{self._airline_key}] {query.departure}->"
                           f"{query.destination}: {len(results)} flights")
        except Exception as e:
            logger.debug(f"[{self._airline_key}] error: {e}")
        finally:
            page.close()
        
        return results
    
    def _parse_response(self, data: dict, query: SearchQuery) -> List[FlightPrice]:
        """Parse airline-specific API response to FlightPrice list."""
        fm = self._config["field_map"]
        now = datetime.now().isoformat()
        results = []
        seen = set()
        
        # Drill into nested data
        items = data
        for key in ["flightList", "flights", "data", "result", "flightInfoList"]:
            if isinstance(items, dict) and key in items:
                items = items[key]
        if not isinstance(items, list):
            return []
        
        for item in items:
            if not isinstance(item, dict):
                continue
            
            fn = self._get_field(item, fm["flightNo"])
            if not fn or fn in seen:
                continue
            seen.add(fn)
            
            price = self._get_field(item, fm["price"])
            try:
                price = float(price) if price else 0
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            
            dep_time = self._get_field(item, fm["depTime"])
            arr_time = self._get_field(item, fm["arrTime"])
            
            results.append(FlightPrice(
                query_id=query.id or 0,
                airline=self._get_field(item, fm["airline"]) or "",
                flight_no=fn,
                aircraft=item.get("aircraftType") or item.get("craftType", ""),
                departure_time=dep_time or "",
                arrival_time=arr_time or "",
                departure_airport=item.get("depAirport") or item.get("departureAirport", query.departure),
                arrival_airport=item.get("arrAirport") or item.get("arrivalAirport", query.destination),
                duration=item.get("duration") or item.get("flyTime", ""),
                stops=item.get("stopCount", 0),
                price=price,
                cabin_class=query.cabin_class,
                source=f"{self._airline_key}_official",
                recorded_at=now,
                purchase_url="",
            ))
        
        return results
    
    @staticmethod
    def _get_field(item: dict, candidates: List[str]) -> str:
        for key in candidates:
            val = item.get(key)
            if val not in (None, "", 0):
                return str(val)
        return ""


# ══════════════════════════════════════════════════════════════
#  Factory: create all configured sources
# ══════════════════════════════════════════════════════════════

def create_airline_sources(airlines: List[str] = None) -> Dict[str, BaseDataSource]:
    """Create scraper instances for specified airlines.
    
    Args:
        airlines: List of airline keys. Default: all configured airlines.
                  e.g. ['airchina', 'csair', 'ceair']
    
    Returns: {source_name: scraper_instance}
    """
    shared = MultiSourceScraper()
    sources = {}
    
    # Trip.com always added
    sources["tripcom"] = TripComSource(shared)
    
    # Add requested airline official sites
    if airlines is None:
        airlines = list(AirlineOfficialSource.AIRLINE_CONFIG.keys())
    
    for key in airlines:
        try:
            sources[f"{key}_official"] = AirlineOfficialSource(key, shared)
        except ValueError:
            logger.warning(f"Skipping unknown airline: {key}")
    
    return sources
