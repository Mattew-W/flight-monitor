"""
Flight Monitor - Ctrip Browser Data Source
Uses Playwright + real Chrome browser to call Ctrip H5 APIs.
This bypasses anti-scraping by using a valid browser session.

Strategy: Navigate to flight list page with route params, intercept the
flightListSearchForH5 API response to extract full flight data (times, airline, price).
Fallback to getLowestPriceCalendar for minimum daily prices.
"""
import json
import logging
import time
from typing import List, Optional
from datetime import datetime
from urllib.parse import quote
from .base import BaseDataSource
from core.models import FlightPrice, SearchQuery

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

CHROME_PATH = r"C:/Program Files/Google/Chrome/Application/chrome.exe"

# City name to Ctrip internal city ID
CITY_TO_CTRIP_ID = {
    "北京": ("BJS", "1"), "上海": ("SHA", "2"), "广州": ("CAN", "31"),
    "深圳": ("SZX", "30"), "成都": ("CTU", "104"), "杭州": ("HGH", "17"),
    "武汉": ("WUH", "477"), "西安": ("XIY", "10"), "重庆": ("CKG", "105"),
    "青岛": ("TAO", "7"), "长沙": ("CSX", "206"), "南京": ("NKG", "15"),
    "厦门": ("XMN", "25"), "昆明": ("KMG", "50"), "大连": ("DLC", "6"),
    "天津": ("TSN", "352"), "郑州": ("CGO", "466"), "三亚": ("SYX", "61"),
    "海口": ("HAK", "59"), "哈尔滨": ("HRB", "5"), "沈阳": ("SHE", "451"),
    "贵阳": ("KWE", "14"), "南宁": ("NNG", "9"), "兰州": ("LHW", "13"),
    "乌鲁木齐": ("URC", "390"), "拉萨": ("LXA", "42"), "银川": ("INC", "99"),
    "西宁": ("XNN", "124"), "呼和浩特": ("HET", "141"), "石家庄": ("SJW", "427"),
    "太原": ("TYN", "101"), "合肥": ("HFE", "102"), "南昌": ("KHN", "103"),
    "济南": ("TNA", "8"), "福州": ("FOC", "23"), "温州": ("WNZ", "463"),
    "宁波": ("NGB", "385"), "烟台": ("YNT", "359"), "威海": ("WEH", "475"),
    "珠海": ("ZUH", "32"), "桂林": ("KWL", "12"), "丽江": ("LJG", "51"),
    "大理": ("DLU", "109"), "敦煌": ("DNH", "11"), "九寨沟": ("JZH", "478"),
    "张家界": ("DYG", "207"), "西双版纳": ("JHG", "53"),
    "香港": ("HKG", "58"), "澳门": ("MFM", "54"), "台北": ("TPE", "617"),
    "高雄": ("KHH", "618"),
    "东京": ("TYO", "233"), "大阪": ("OSA", "231"), "名古屋": ("NGO", "569"),
    "福冈": ("FUK", "677"), "札幌": ("SPK", "622"), "冲绳": ("OKA", "428"),
    "首尔": ("SEL", "222"), "釜山": ("PUS", "237"), "济州岛": ("CJU", "489"),
    "新加坡": ("SIN", "93"), "曼谷": ("BKK", "140"), "吉隆坡": ("KUL", "127"),
    "河内": ("HAN", "571"), "胡志明市": ("SGN", "291"), "雅加达": ("CGK", "468"),
    "马尼拉": ("MNL", "285"),
    "迪拜": ("DXB", "18"), "多哈": ("DOH", "902"),
    "伦敦": ("LON", "69"), "巴黎": ("PAR", "71"), "法兰克福": ("FRA", "80"),
    "阿姆斯特丹": ("AMS", "87"), "罗马": ("ROM", "92"),
    "纽约": ("NYC", "72"), "洛杉矶": ("LAX", "74"), "旧金山": ("SFO", "75"),
    "芝加哥": ("ORD", "106"), "波士顿": ("BOS", "453"),
    "多伦多": ("YTO", "457"), "温哥华": ("YVR", "458"),
    "悉尼": ("SYD", "73"), "墨尔本": ("MEL", "259"),
}

# Old mapping for backward compat
CITY_TO_IATA = {k: v[0] for k, v in CITY_TO_CTRIP_ID.items()}


class CtripBrowserSource(BaseDataSource):
    """Ctrip (携程) data source using Playwright browser session."""

    name = "ctrip_browser"

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT

    def _init_browser(self):
        """Initialize browser session with stable headless mode."""
        if self._browser:
            return
        
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            executable_path=CHROME_PATH,
            args=[
                "--headless=new",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--window-size=375,812",
                "--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/16.0 Mobile/15E148 Safari/604.1",
            ],
        )
        self._context = self._browser.new_context(
            viewport={"width": 375, "height": 812},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/16.0 Mobile/15E148 Safari/604.1",
            locale="zh-CN",
        )
        self._page = self._context.new_page()
        # Visit homepage to establish session
        self._page.goto("https://m.ctrip.com/html5/flight/swift/", wait_until="domcontentloaded")
        self._page.wait_for_timeout(5000)

    def _close_browser(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """
        Search flights by navigating to the flight list page and
        intercepting the flightListSearchForH5 API response.
        This gives full flight data: airline, flight_no, departure/arrival times, price.
        """
        if not self.is_available():
            return []

        city_info = CITY_TO_CTRIP_ID.get(query.departure)
        if not city_info:
            logger.warning(f"CtripBrowserSource: Unknown city: {query.departure}")
            return []
        dep_code, dep_id = city_info

        city_info2 = CITY_TO_CTRIP_ID.get(query.destination)
        if not city_info2:
            logger.warning(f"CtripBrowserSource: Unknown city: {query.destination}")
            return []
        arr_code, arr_id = city_info2

        try:
            self._init_browser()
        except Exception as e:
            logger.error(f"CtripBrowserSource: Browser init failed: {e}")
            return []

        flight_data = []

        # Use route interception instead of response listener to catch ALL requests
        all_urls = set()

        def on_response(response):
            nonlocal flight_data, all_urls
            url = response.url
            if response.status == 200:
                all_urls.add(url[:200])

            if "flightListSearchForH5" in url and response.status == 200:
                try:
                    data = response.json()
                    flt_item = data.get("fltitem", [])
                    if isinstance(flt_item, list) and flt_item:
                        flight_data = flt_item
                        logger.info(f"CtripBrowserSource: Intercepted {len(flt_item)} flights from flightList")
                except Exception as e:
                    logger.warning(f"CtripBrowserSource: Failed to parse flight list: {e}")

            if "flightGloryList" in url and response.status == 200:
                try:
                    data = response.json()
                    logger.info(f"CtripBrowserSource: flightGloryList response keys: {list(data.keys())[:10]}")
                except Exception as e:
                    logger.warning(f"CtripBrowserSource: flightGloryList parse failed: {e}")

            if "getLowestPriceCalendar" in url and response.status == 200:
                try:
                    data = response.json()
                    raw = data.get("data", "")
                    if raw:
                        flights = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(flights, list):
                            # Save calendar data for fallback if flightList data is unavailable
                            cal_flights = [{"price": f.get("price", 0), "airlineName": f.get("airlineName", ""),
                                          "flightNo": f.get("flightNo", ""), "departureCityCode": f.get("departureCityCode", ""),
                                          "arrivalCityCode": f.get("arrivalCityCode", "")} for f in flights]
                            if not flight_data:
                                flight_data = cal_flights
                            logger.info(f"CtripBrowserSource: Intercepted {len(flights)} flights from calendar API")
                except Exception as e:
                    logger.warning(f"CtripBrowserSource: Calendar parse failed: {e}")

        self._page.on("response", on_response)

        # Also log all XHR requests to find the flight list API
        def on_request(request):
            url = request.url
            if "restapi/soa2" in url or "flightList" in url or "flightlist" in url.lower():
                all_urls.add(f"REQ:{url[:250]}")
        self._page.on("request", on_request)

        try:
            # Navigate to flight list page with route params
            dep_enc = quote(query.departure)
            arr_enc = quote(query.destination)
            search_url = (
                f"https://m.ctrip.com/html5/flight/swift/list"
                f"?dcity={dep_enc}&acity={arr_enc}"
                f"&ddate={query.departure_date}&cabin=Y_S&adult=1&child=0&infant=0"
            )

            logger.info(f"CtripBrowserSource: Navigating to flight list page...")
            self._page.goto(search_url, wait_until="domcontentloaded")
            self._page.wait_for_timeout(15000)
        finally:
            self._page.remove_listener("response", on_response)
            self._page.remove_listener("request", on_request)

        if not flight_data:
            logger.warning("CtripBrowserSource: No flight list data intercepted")
        # Always log intercepted URLs for debugging
        flight_urls = [u for u in all_urls if "flight" in u.lower() or "search" in u.lower() or "api" in u.lower() or "json" in u.lower()]
        if flight_urls:
            logger.info(f"CtripBrowserSource: Intercepted {len(all_urls)} URLs, {len(flight_urls)} flight-related:")
            for u in sorted(flight_urls)[:8]:
                logger.info(f"  {u}")

        # Convert API response to FlightPrice objects
        now = datetime.now().isoformat()
        result = []
        for item in flight_data:
            try:
                if not isinstance(item, dict):
                    continue

                airline_name = ""
                flight_no = ""
                dep_airport = ""
                arr_airport = ""
                dep_time = ""
                arr_time = ""
                aircraft = ""
                stops = 0
                lowest_price = 0

                # Handle flightListSearchForH5 format
                mutilstn = item.get("mutilstn", [])
                if mutilstn and isinstance(mutilstn, list) and len(mutilstn) > 0:
                    seg = mutilstn[0]
                    if isinstance(seg, dict):
                        basinfo = seg.get("basinfo", {})
                        dportinfo = seg.get("dportinfo", {})
                        aportinfo = seg.get("aportinfo", {})
                        dateinfo = seg.get("dateinfo", {})
                        craftinfo = seg.get("craftinfo", {})

                        flight_no = basinfo.get("flgno", "")
                        airline_code = basinfo.get("aircode", "")
                        airline_name = basinfo.get("airlineName", airline_code)
                        dep_airport = dportinfo.get("aport", dep_code)
                        arr_airport = aportinfo.get("aport", arr_code)
                        dep_time = dateinfo.get("ddate", "")
                        arr_time = dateinfo.get("adate", "")
                        aircraft = craftinfo.get("cdisname", "")
                        stops = dateinfo.get("dcnt", 0)

                        # Get price from policyinfo
                        policyinfo = item.get("policyinfo", [])
                        for pol in policyinfo:
                            if isinstance(pol, dict):
                                price_val = pol.get("tprice", 0)
                                if price_val and price_val > 0:
                                    lowest_price = price_val
                                    break

                # Handle calendar API format (getLowestPriceCalendar fallback)
                elif "airlineName" in item and "price" in item:
                    airline_name = item.get("airlineName", "")
                    flight_no = item.get("flightNo", "")
                    lowest_price = float(item.get("price", 0))
                    dep_airport = item.get("departureCityCode", dep_code)
                    arr_airport = item.get("arrivalCityCode", arr_code)
                    # Calendar API doesn't have times, use empty strings
                    dep_time = ""
                    arr_time = ""

                if not lowest_price or lowest_price <= 0:
                    continue

                result.append(FlightPrice(
                    query_id=query.id or 0,
                    airline=airline_name or airline_code or "未知航司",
                    flight_no=flight_no or "",
                    aircraft=aircraft or "",
                    departure_time=dep_time.split(" ")[1] if " " in dep_time else dep_time,
                    arrival_time=arr_time.split(" ")[1] if " " in arr_time else arr_time,
                    departure_airport=dep_airport,
                    arrival_airport=arr_airport,
                    duration="",
                    stops=int(stops) if stops else 0,
                    price=float(lowest_price),
                    cabin_class=query.cabin_class,
                    source=self.name,
                    recorded_at=now,
                    purchase_url=(
                        f"https://flights.ctrip.com/online/list/oneway-{dep_code}-{arr_code}"
                        f"?depdate={query.departure_date}&cabin=y_s&adult=1&child=0&infant=0"
                    ),
                ))
            except Exception as e:
                logger.warning(f"CtripBrowserSource: Failed to parse flight item: {e}")
                continue

        logger.info(f"CtripBrowserSource: Converted {len(result)} flights")
        return result

    def __del__(self):
        self._close_browser()
