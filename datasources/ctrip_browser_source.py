"""
Flight Monitor - Ctrip Browser Data Source (Enhanced)
Uses Playwright + real Chrome browser to call Ctrip H5 APIs.
Features dynamic scrolling for full data loading and robust JSON extraction.
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

CITY_TO_IATA = {k: v[0] for k, v in CITY_TO_CTRIP_ID.items()}


class CtripBrowserSource(BaseDataSource):
    name = "ctrip_browser"

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._last_used = 0.0
        self._max_idle_seconds = 60

    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT

    def _ensure_browser(self):
        now = time.time()
        if self._browser and (now - self._last_used) > self._max_idle_seconds:
            logger.info("CtripBrowserSource: Browser idle too long, closing...")
            self._close_browser()
        if not self._browser:
            self._init_browser()
        self._last_used = time.time()

    def _init_browser(self):
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
        page = self._context.new_page()
        page.goto("https://m.ctrip.com/html5/flight/swift/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.close()

    def _close_browser(self):
        try:
            if self._context: self._context.close()
            if self._browser: self._browser.close()
            if self._playwright: self._playwright.stop()
        except Exception:
            pass
        self._browser, self._context = None, None

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        if not self.is_available():
            return []

        city_info = CITY_TO_CTRIP_ID.get(query.departure)
        city_info2 = CITY_TO_CTRIP_ID.get(query.destination)
        if not city_info or not city_info2:
            logger.warning("CtripBrowserSource: Unknown city mapping.")
            return []

        dep_code, dep_id = city_info
        arr_code, arr_id = city_info2

        try:
            self._ensure_browser()
        except Exception as e:
            logger.error(f"CtripBrowserSource: Browser init failed: {e}")
            return []

        page = self._context.new_page()
        try:
            return self._do_search(page, query, dep_code, arr_code)
        finally:
            page.close()

    def _do_search(self, page, query, dep_code, arr_code):
        flight_data_map = {}
        api_intercepted = False

        def on_response(response):
            nonlocal api_intercepted
            url = response.url
            if response.status != 200:
                return

            # Intercept both flightListSearchForH5 and flightGloryList (with times)
            # Also keep getLowestPriceCalendar as fallback for flight count
            if "flightListSearchForH5" in url or "flightGloryList" in url:
                try:
                    data = response.json()
                    raw_items = data.get("fltitem", []) or data.get("finfo", [])
                    if raw_items and isinstance(raw_items, list) and len(raw_items) > 0:
                        api_intercepted = True
                        for item in raw_items:
                            self._extract_flight(item, flight_data_map, dep_code, arr_code, query)
                except Exception as e:
                    logger.warning(f"CtripBrowserSource: Parse error on {url[:100]}: {e}")

            elif "getLowestPriceCalendar" in url:
                try:
                    data = response.json()
                    raw = data.get("data", "")
                    if raw:
                        flights = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(flights, list) and flights:
                            for item in flights:
                                self._extract_flight(item, flight_data_map, dep_code, arr_code, query)
                except Exception as e:
                    logger.warning(f"CtripBrowserSource: Calendar parse failed: {e}")

        page.on("response", on_response)

        try:
            dep_enc = quote(query.departure)
            arr_enc = quote(query.destination)
            search_url = (
                f"https://m.ctrip.com/html5/flight/swift/list"
                f"?dcity={dep_enc}&acity={arr_enc}"
                f"&ddate={query.departure_date}&cabin=Y_S&adult=1&child=0&infant=0"
            )

            logger.info("CtripBrowserSource: Loading flight list...")
            page.goto(search_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # Dynamic scroll to trigger lazy loading
            last_height = page.evaluate("document.body.scrollHeight")
            for _ in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    page.wait_for_response(
                        lambda r: "flightListSearch" in r.url and r.status == 200,
                        timeout=2000)
                except Exception:
                    page.wait_for_timeout(1000)

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

        finally:
            page.remove_listener("response", on_response)

        if not api_intercepted:
            logger.info("CtripBrowserSource: Timed flights not available, "
                       "using calendar data as fallback")

        results = list(flight_data_map.values())
        logger.info(f"CtripBrowserSource: Parsed {len(results)} distinct flights.")
        return results

    def _extract_flight(self, item: dict, data_map: dict,
                       default_dep: str, default_arr: str, query: SearchQuery):
        """Robust flight extraction with bsname-first airport names."""
        if not isinstance(item, dict):
            return

        flight_no = ""
        airline_name = ""
        dep_airport = ""
        arr_airport = ""
        dep_time = ""
        arr_time = ""
        aircraft = ""
        stops = 0
        lowest_price = 0

        # ---- Parse flightListSearchForH5 / flightGloryList structure ----
        mutilstn = item.get("mutilstn", [])
        if mutilstn and isinstance(mutilstn, list):
            seg = mutilstn[0]
            if isinstance(seg, dict):
                basinfo = seg.get("basinfo", {})
                dportinfo = seg.get("dportinfo", {})
                aportinfo = seg.get("aportinfo", {})
                dateinfo = seg.get("dateinfo", {})
                craftinfo = seg.get("craftinfo", {})

                flight_no = basinfo.get("flgno", "")
                airline_name = basinfo.get("airlineName") or basinfo.get("aircode", "")

                # Preferred: Chinese airport name (bsname), then code (aport), then city
                dep_airport = dportinfo.get("bsname") or dportinfo.get("aport") or default_dep
                arr_airport = aportinfo.get("bsname") or aportinfo.get("aport") or default_arr

                dep_time_raw = dateinfo.get("ddate", "")
                arr_time_raw = dateinfo.get("adate", "")
                dep_time = dep_time_raw.split(" ")[1][:5] if " " in dep_time_raw else dep_time_raw
                arr_time = arr_time_raw.split(" ")[1][:5] if " " in arr_time_raw else arr_time_raw

                aircraft = craftinfo.get("cdisname", "")
                stops = dateinfo.get("dcnt", 0)

                for pol in item.get("policyinfo", []):
                    price_val = pol.get("tprice", 0)
                    if price_val > 0:
                        lowest_price = price_val
                        break

        # ---- Parse flightGloryList rich format ----
        elif "departureTime" in item or "arrivalTime" in item:
            flight_no = item.get("flightNo", "")
            airline_name = item.get("airlineName", "")
            lowest_price = float(item.get("lowestPrice") or item.get("price", 0))

            dep_airport = item.get("departureAirportName") or item.get("departureCityCode") or default_dep
            arr_airport = item.get("arrivalAirportName") or item.get("arrivalCityCode") or default_arr

            dep_time_raw = item.get("departureTime", "")
            arr_time_raw = item.get("arrivalTime", "")
            dep_time = dep_time_raw.split(" ")[1][:5] if " " in dep_time_raw else \
                (dep_time_raw.split("T")[-1][:5] if "T" in dep_time_raw else dep_time_raw)
            arr_time = arr_time_raw.split(" ")[1][:5] if " " in arr_time_raw else \
                (arr_time_raw.split("T")[-1][:5] if "T" in arr_time_raw else arr_time_raw)

            aircraft = item.get("aircraftName", "")

        # ---- Calendar API fallback (airlineName + price, no times) ----
        elif "airlineName" in item and ("price" in item or "lowestPrice" in item):
            airline_name = item.get("airlineName", "")
            flight_no = item.get("flightNo", "")
            lowest_price = float(item.get("price") or item.get("lowestPrice", 0))
            dep_airport = item.get("departureCityCode", default_dep)
            arr_airport = item.get("arrivalCityCode", default_arr)
            dep_time = ""
            arr_time = ""

        # Discard invalid data
        if not lowest_price or lowest_price <= 0 or not flight_no:
            return

        now = datetime.now().isoformat()
        purchase_url = (
            f"https://flights.ctrip.com/online/list/oneway-{default_dep}-{default_arr}"
            f"?depdate={query.departure_date}&cabin=y_s&adult=1&child=0&infant=0"
        )

        # Keep only the lowest price per flight_no
        unique_key = f"{flight_no}_{dep_time}" if dep_time else flight_no
        if unique_key not in data_map or lowest_price < data_map[unique_key].price:
            data_map[unique_key] = FlightPrice(
                query_id=query.id or 0,
                airline=airline_name or "未知航司",
                flight_no=flight_no,
                aircraft=aircraft,
                departure_time=dep_time,
                arrival_time=arr_time,
                departure_airport=dep_airport,
                arrival_airport=arr_airport,
                duration="",
                stops=int(stops) if stops else 0,
                price=float(lowest_price),
                cabin_class=query.cabin_class,
                source=self.name,
                recorded_at=now,
                purchase_url=purchase_url,
            )

    def __del__(self):
        self._close_browser()
