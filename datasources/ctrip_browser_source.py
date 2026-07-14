"""
Flight Monitor - Ctrip Browser Data Source (v3)
Real browser scraping via Playwright with:
- Exponential backoff retry (3 attempts)
- Thread-safe browser access
- Configurable timeout
- Response deduplication
- Anti-detection measures
"""
import json
import logging
import os
import random
import threading
import time
from typing import List, Optional, Dict, Set
from datetime import datetime
from urllib.parse import quote
from .base import BaseDataSource
from core.models import FlightPrice, SearchQuery

# Lazy import for schedule backfill
_flight_schedules_loaded = False
_lookup_flight_schedule = None

def _get_schedule_lookup():
    global _flight_schedules_loaded, _lookup_flight_schedule
    if not _flight_schedules_loaded:
        try:
            from .flight_schedules import lookup_flight_schedule as lfs
            _lookup_flight_schedule = lfs
        except ImportError:
            _lookup_flight_schedule = lambda fn: None
        _flight_schedules_loaded = True
    return _lookup_flight_schedule

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# ── Config ──────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0        # seconds, doubles each retry
SEARCH_TIMEOUT_SECONDS = 25   # total search timeout
SCROLL_PASSES = 5             # max scroll passes for lazy loading
IDLE_CLOSE_SECONDS = 120      # close browser after this idle time
INIT_WARMUP_WAIT = 2.0        # warm-up wait after browser init
SEARCH_DELAY_SEC = (2.0, 5.0) # random delay between searches (anti-rate-limit)

CHROME_PATHS = [
    os.environ.get("CHROME_PATH", ""),
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]

for _p in CHROME_PATHS:
    if _p and os.path.exists(_p):
        CHROME_PATH = _p
        break
else:
    CHROME_PATH = None  # let Playwright use its own chromium


# ── City mapping ─────────────────────────────────────────────────
CITY_TO_CTRIP_ID: Dict[str, tuple] = {
    # 国内
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
    # 日韩
    "东京": ("TYO", "233"), "大阪": ("OSA", "231"), "名古屋": ("NGO", "569"),
    "福冈": ("FUK", "677"), "札幌": ("SPK", "622"), "冲绳": ("OKA", "428"),
    "首尔": ("SEL", "222"), "釜山": ("PUS", "237"), "济州岛": ("CJU", "489"),
    # 东南亚
    "新加坡": ("SIN", "93"), "曼谷": ("BKK", "140"), "吉隆坡": ("KUL", "127"),
    "河内": ("HAN", "571"), "胡志明市": ("SGN", "291"), "雅加达": ("CGK", "468"),
    "马尼拉": ("MNL", "285"),
    # 中东
    "迪拜": ("DXB", "18"), "多哈": ("DOH", "902"),
    # 欧洲
    "伦敦": ("LON", "69"), "巴黎": ("PAR", "71"), "法兰克福": ("FRA", "80"),
    "阿姆斯特丹": ("AMS", "87"), "罗马": ("ROM", "92"),
    # 北美
    "纽约": ("NYC", "72"), "洛杉矶": ("LAX", "74"), "旧金山": ("SFO", "75"),
    "芝加哥": ("ORD", "106"), "波士顿": ("BOS", "453"),
    "多伦多": ("YTO", "457"), "温哥华": ("YVR", "458"),
    # 大洋洲
    "悉尼": ("SYD", "73"), "墨尔本": ("MEL", "259"),
}


class CtripBrowserSource(BaseDataSource):
    """Ctrip flight search via Playwright browser.

    Two modes:
      - fresh_per_search=True (default): new browser each search, avoid rate limiting
      - fresh_per_search=False: reuse browser, faster but triggers anti-bot quickly
    """

    name = "ctrip_browser"

    def __init__(self, fresh_per_search: bool = True, proxy: str = None):
        self._fresh_per_search = fresh_per_search
        self._proxy = proxy or os.environ.get("CTRIP_PROXY", "")
        # Reuse-mode only
        self._playwright = None
        self._browser = None
        self._context = None
        self._lock = threading.Lock()
        self._last_used = 0.0

    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT

    # ── Fresh-per-search: create + destroy browser each call ──

    def _search_fresh(self, query, dep_code, arr_code) -> List[FlightPrice]:
        """Create a fresh browser instance, search once, destroy."""
        pw = sync_playwright().start()
        try:
            launch_kw = {
                "headless": True,
                "args": [
                    "--headless=new",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--window-size=375,812",
                ],
            }
            if CHROME_PATH:
                launch_kw["executable_path"] = CHROME_PATH
            if self._proxy:
                launch_kw["proxy"] = {"server": self._proxy}

            browser = pw.chromium.launch(**launch_kw)
            ctx = browser.new_context(
                viewport={"width": 375, "height": 812},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/16.0 Mobile/15E148 Safari/604.1"
                ),
                locale="zh-CN",
            )
            self._load_cookies_into(ctx)
            page = ctx.new_page()
            try:
                return self._do_search(page, query, dep_code, arr_code)
            finally:
                page.close()
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

    # ── Reuse mode: keep browser alive ────────────────────────

    def _ensure_browser(self) -> bool:
        with self._lock:
            now = time.time()
            if self._browser and (now - self._last_used) > IDLE_CLOSE_SECONDS:
                self._close_browser_nolock()
            if not self._browser:
                ok = self._init_browser_nolock()
                if not ok:
                    return False
            self._last_used = now
            return True

    def _init_browser_nolock(self) -> bool:
        if self._browser:
            return True
        try:
            self._playwright = sync_playwright().start()
            launch_kw = {"headless": True, "args": [
                "--headless=new", "--disable-blink-features=AutomationControlled",
                "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--window-size=375,812",
            ]}
            if CHROME_PATH:
                launch_kw["executable_path"] = CHROME_PATH
            if self._proxy:
                launch_kw["proxy"] = {"server": self._proxy}
            self._browser = self._playwright.chromium.launch(**launch_kw)
            self._context = self._browser.new_context(
                viewport={"width": 375, "height": 812},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/16.0 Mobile/15E148 Safari/604.1"
                ),
                locale="zh-CN",
            )
            self._load_cookies_into(self._context)
            page = self._context.new_page()
            page.goto("https://m.ctrip.com/html5/flight/swift/",
                      wait_until="domcontentloaded", timeout=10000)
            time.sleep(INIT_WARMUP_WAIT)
            page.close()
            logger.info("CtripBrowserSource: browser initialized (reuse mode)")
            return True
        except Exception as e:
            logger.error(f"CtripBrowserSource: init failed: {e}")
            self._close_browser_nolock()
            return False

    def _load_cookies_into(self, context):
        cookie_file = os.path.join(os.path.dirname(__file__), "..", "ctrip_cookies.json")
        if not os.path.exists(cookie_file):
            return
        try:
            with open(cookie_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
                logger.debug(f"CtripBrowserSource: loaded {len(cookies)} cookies")
        except Exception as e:
            logger.debug(f"CtripBrowserSource: cookie skip ({e})")

    def _close_browser_nolock(self):
        for obj in (self._context, self._browser, self._playwright):
            if obj:
                try:
                    obj.close() if hasattr(obj, 'close') else obj.stop()
                except Exception:
                    pass
        self._context = self._browser = self._playwright = None

    def close(self):
        with self._lock:
            self._close_browser_nolock()

    # ── Main search ───────────────────────────────────────────

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        if not self.is_available():
            return []

        city_info = CITY_TO_CTRIP_ID.get(query.departure)
        city_info2 = CITY_TO_CTRIP_ID.get(query.destination)
        if not city_info or not city_info2:
            logger.warning(f"CtripBrowserSource: no city mapping for "
                           f"{query.departure}->{query.destination}")
            return []

        dep_code, dep_id = city_info
        arr_code, arr_id = city_info2

        # ── Fresh-per-search: new browser each time ──
        if self._fresh_per_search:
            try:
                results = self._search_fresh(query, dep_code, arr_code)
                if results:
                    return results
                # 0 results = IP-level rate limit, retrying won't help
                return []
            except Exception as e:
                logger.warning(f"CtripBrowserSource (fresh): {e}")
                return []

        # ── Reuse mode: keep browser alive ──
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if not self._ensure_browser():
                    raise RuntimeError("Browser init failed")
                if attempt > 1:
                    time.sleep(random.uniform(*SEARCH_DELAY_SEC))
                page = self._context.new_page()
                try:
                    results = self._do_search(page, query, dep_code, arr_code)
                    if results:
                        return results
                    logger.info("CtripBrowserSource: 0 results")
                    return []
                finally:
                    page.close()
            except Exception as e:
                logger.warning(f"CtripBrowserSource attempt "
                               f"{attempt}/{MAX_RETRIES}: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
        return []

    # ── Core search logic ─────────────────────────────────────

    def _do_search(self, page, query, dep_code: str, arr_code: str) -> List[FlightPrice]:
        flight_data_map: Dict[str, FlightPrice] = {}
        api_intercepted = False
        seen_flight_nos: Set[str] = set()

        def on_response(response):
            nonlocal api_intercepted
            url = response.url
            if response.status != 200:
                return

            for api_pattern in ("flightListSearchForH5", "flightGloryList"):
                if api_pattern in url:
                    try:
                        data = response.json()
                        items = (data.get("fltitem") or data.get("finfo") or [])
                        if isinstance(items, list):
                            for item in items:
                                entry = self._extract_flight(
                                    item, dep_code, arr_code, query, seen_flight_nos
                                )
                                if entry:
                                    api_intercepted = True
                                    key = f"{entry.flight_no}_{entry.departure_time}"
                                    if key not in flight_data_map or \
                                       entry.price < flight_data_map[key].price:
                                        flight_data_map[key] = entry
                    except Exception as e:
                        logger.debug(f"CtripBrowserSource: parse error: {e}")
                    break

        page.on("response", on_response)

        try:
            dep_enc = quote(query.departure)
            arr_enc = quote(query.destination)
            search_url = (
                f"https://m.ctrip.com/html5/flight/swift/list"
                f"?dcity={dep_enc}&acity={arr_enc}"
                f"&ddate={query.departure_date}&cabin=Y_S"
                f"&adult=1&child=0&infant=0"
            )

            logger.debug(f"CtripBrowserSource: searching "
                         f"{query.departure}->{query.destination} on {query.departure_date}")
            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)

            # Scroll to trigger lazy-loaded API calls
            last_height = page.evaluate("document.body.scrollHeight")
            for _ in range(SCROLL_PASSES):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    page.wait_for_response(
                        lambda r: "flightListSearch" in r.url and r.status == 200,
                        timeout=2000,
                    )
                except Exception:
                    page.wait_for_timeout(1000)
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

        finally:
            page.remove_listener("response", on_response)

        # DOM fallback: if API returned empty, try to extract from rendered page
        if not flight_data_map:
            logger.debug("CtripBrowserSource: API empty, trying DOM fallback...")
            try:
                import re
                html = page.content()
                pattern = re.compile(
                    r'([A-Z0-9]{2}\d{2,4})[^A-Z]{0,60}?'
                    r'([\u4e00-\u9fff]{2,6}(?:航空|国际|航司|Jet|Air|Airlines))'
                    r'[^¥]{0,40}?¥\s*(\d{3,6})',
                    re.DOTALL | re.UNICODE,
                )
                dom_count = 0
                for m in pattern.finditer(html):
                    if dom_count >= 30:
                        break
                    fn_key = m.group(1)
                    if fn_key in seen_flight_nos:
                        continue
                    seen_flight_nos.add(fn_key)
                    try:
                        price = float(m.group(3))
                        if price < 100:
                            continue
                        entry = FlightPrice(
                            query_id=query.id or 0,
                            airline=m.group(2),
                            flight_no=fn_key,
                            aircraft="",
                            departure_time="", arrival_time="",
                            departure_airport=query.departure,
                            arrival_airport=query.destination,
                            duration="", stops=0, price=price,
                            cabin_class=query.cabin_class or "economy",
                            source=self.name,
                            recorded_at=datetime.now().isoformat(),
                            purchase_url=page.url,
                        )
                        lookup = _get_schedule_lookup()
                        sched = lookup(fn_key)
                        if sched:
                            entry.departure_time = sched["dep"]
                            entry.arrival_time = sched["arr"]
                            dm = sched["duration_min"]
                            entry.duration = f"{dm // 60}h{dm % 60}m"
                            entry.aircraft = sched.get("aircraft", "")
                        flight_data_map[fn_key] = entry
                        dom_count += 1
                    except ValueError:
                        continue
                logger.debug(f"CtripBrowserSource: DOM extracted {dom_count} flights")
            except Exception as e:
                logger.debug(f"CtripBrowserSource: DOM fallback error: {e}")

        results = list(flight_data_map.values())
        if results or api_intercepted:
            logger.info(f"CtripBrowserSource: {len(results)} flights "
                        f"(intercepted={'yes' if api_intercepted else 'no'})")
        return results

    # ── Flight extraction ─────────────────────────────────────

    def _extract_flight(self, item: dict, default_dep: str, default_arr: str,
                        query: SearchQuery, seen: Set[str]) -> Optional[FlightPrice]:
        """Parse one flight record from any supported Ctrip API response format."""
        if not isinstance(item, dict):
            return None

        flight_no = airline_name = dep_airport = arr_airport = ""
        dep_time = arr_time = aircraft = duration = ""
        stops = 0
        lowest_price = 0.0

        # ── Format 1: flightListSearchForH5 / flightGloryList ──
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
                dep_airport = dportinfo.get("bsname") or dportinfo.get("aport") or default_dep
                arr_airport = aportinfo.get("bsname") or aportinfo.get("aport") or default_arr

                dt_raw = dateinfo.get("ddate", "")
                at_raw = dateinfo.get("adate", "")
                dep_time = dt_raw.split(" ")[1][:5] if " " in dt_raw else dt_raw
                arr_time = at_raw.split(" ")[1][:5] if " " in at_raw else at_raw
                aircraft = craftinfo.get("cdisname", "")
                stops = int(dateinfo.get("dcnt", 0))

                # Direct duration from API
                dur_raw = (seg.get("duration") or seg.get("durationMin") or
                           dateinfo.get("duration") or dateinfo.get("durdiff", 0))
                if dur_raw and float(dur_raw) > 0:
                    dmin = int(float(dur_raw))
                    duration = f"{dmin // 60}h{dmin % 60}m"

                for pol in item.get("policyinfo", []):
                    pv = pol.get("tprice", 0)
                    if pv and float(pv) > 0:
                        lowest_price = float(pv)
                        break

        # ── Format 2: flightGloryList rich format ──
        elif "departureTime" in item or "arrivalTime" in item:
            flight_no = item.get("flightNo", "")
            airline_name = item.get("airlineName", "")
            lowest_price = float(item.get("lowestPrice") or item.get("price", 0))

            dep_airport = (item.get("departureAirportName") or
                           item.get("departureCityCode") or default_dep)
            arr_airport = (item.get("arrivalAirportName") or
                           item.get("arrivalCityCode") or default_arr)

            for raw, field in [("departureTime", "dep"), ("arrivalTime", "arr")]:
                rv = item.get(raw, "")
                for sep in (" ", "T"):
                    if sep in rv:
                        rv = rv.split(sep)[-1][:5]
                        break
                if field == "dep":
                    dep_time = rv
                else:
                    arr_time = rv
            aircraft = item.get("aircraftName", "")
            # Direct duration from API
            dur_raw = item.get("flightDuration") or item.get("durationMin") or item.get("duration", 0)
            if dur_raw and float(dur_raw) > 0:
                dmin = int(float(dur_raw))
                duration = f"{dmin // 60}h{dmin % 60}m"

        # ── Format 3: Calendar API fallback (minimal) ──
        elif "airlineName" in item and ("price" in item or "lowestPrice" in item):
            airline_name = item.get("airlineName", "")
            flight_no = item.get("flightNo", "")
            lowest_price = float(item.get("price") or item.get("lowestPrice", 0))
            dep_airport = item.get("departureCityCode", default_dep)
            arr_airport = item.get("arrivalCityCode", default_arr)
            # Calendar API may also contain time fields in some versions
            dep_time = item.get("departureTime", "") or item.get("dtime", "")
            arr_time = item.get("arrivalTime", "") or item.get("atime", "")

        # ── Format 4: Generic fallback ──
        elif "flightNo" in item and "price" in item:
            flight_no = item.get("flightNo", "")
            airline_name = item.get("airlineName", "")
            lowest_price = float(item.get("price", 0))
            dep_airport = item.get("departureCityCode", default_dep)
            arr_airport = item.get("arrivalCityCode", default_arr)
            dep_time = item.get("departureTime", "") or item.get("dtime", "")
            arr_time = item.get("arrivalTime", "") or item.get("atime", "")

        # ── Validation ──
        if not lowest_price or lowest_price <= 0:
            return None
        if not flight_no:
            return None
        if not airline_name:
            airline_name = "未知航司"

        # Deduplicate
        dedup_key = flight_no
        if dedup_key in seen:
            return None
        seen.add(dedup_key)

        # ── Backfill from static schedule if time/duration missing ──
        if (not dep_time or not arr_time or not duration) and flight_no:
            lookup = _get_schedule_lookup()
            sched = lookup(flight_no)
            if sched:
                dep_time = dep_time or sched["dep"]
                arr_time = arr_time or sched["arr"]
                if not duration:
                    dm = sched["duration_min"]
                    duration = f"{dm // 60}h{dm % 60}m"
                if not aircraft:
                    aircraft = sched.get("aircraft", "")

        # ── Calculate duration from times if still missing ──
        if not duration and dep_time and arr_time:
            try:
                def _to_minutes(t: str) -> int:
                    t = t.strip().replace(":", "")
                    if len(t) >= 4:
                        return int(t[:2]) * 60 + int(t[2:4])
                    return 0
                dep_m = _to_minutes(dep_time)
                arr_m = _to_minutes(arr_time)
                if dep_m and arr_m:
                    diff = arr_m - dep_m
                    if diff < 0:
                        diff += 24 * 60
                    hours, minutes = divmod(diff, 60)
                    duration = f"{hours}h{minutes}m"
            except Exception:
                pass

        return FlightPrice(
            query_id=query.id or 0,
            airline=airline_name,
            flight_no=flight_no,
            aircraft=aircraft,
            departure_time=dep_time,
            arrival_time=arr_time,
            departure_airport=dep_airport,
            arrival_airport=arr_airport,
            duration=duration,
            stops=stops,
            price=lowest_price,
            cabin_class=query.cabin_class or "economy",
            source=self.name,
            recorded_at=datetime.now().isoformat(),
            purchase_url=purchase_url,
        )

    def __del__(self):
        self.close()
