"""
Ctrip Browser Data Source (v4 — Async)
Real flight scraping via shared async browser pool.
"""
import asyncio
import logging
import os
import re
import random
from typing import List, Optional, Dict, Set
from datetime import datetime
from urllib.parse import quote
from .base import BaseDataSource, register_source
from core.models import FlightPrice, SearchQuery

logger = logging.getLogger(__name__)

# Lazy schedule backfill
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


SCROLL_PASSES = 5
SEARCH_TIMEOUT_SECONDS = 25


# ── City mapping ─────────────────────────────────────────────────
CITY_TO_CTRIP_ID: Dict[str, tuple] = {
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
    "东京": ("TYO", "233"), "大阪": ("OSA", "231"), "名古屋": ("NGO", "569"),
    "首尔": ("SEL", "222"), "新加坡": ("SIN", "93"), "曼谷": ("BKK", "140"),
    "吉隆坡": ("KUL", "127"), "迪拜": ("DXB", "18"), "多哈": ("DOH", "902"),
    "伦敦": ("LON", "69"), "巴黎": ("PAR", "71"), "法兰克福": ("FRA", "80"),
    "纽约": ("NYC", "72"), "洛杉矶": ("LAX", "74"), "旧金山": ("SFO", "75"),
    "悉尼": ("SYD", "73"), "墨尔本": ("MEL", "259"),
}


@register_source("ctrip_browser")
class CtripBrowserSource(BaseDataSource):
    """Ctrip flight search via shared async browser pool."""

    name = "ctrip_browser"

    def is_available(self) -> bool:
        return True  # pool handles Playwright check

    async def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Async search flights via shared browser pool."""
        city = CITY_TO_CTRIP_ID.get(query.departure)
        city2 = CITY_TO_CTRIP_ID.get(query.destination)
        if not city or not city2:
            return []
        dep_code, _ = city
        arr_code, _ = city2

        try:
            from core.browser_pool import get_browser_pool
            pool = await get_browser_pool()
            page = await pool.new_page("ctrip")
            if page is None:
                return []
            try:
                return await self._do_search(page, query, dep_code, arr_code)
            finally:
                await pool.close_page(page)
        except Exception as e:
            logger.warning(f"CtripBrowserSource async: {e}")
            return []

    async def search_flights_with_page(self, page, query: SearchQuery,
                                        page_timeout_ms: int = 20000,
                                        wait_after_load_ms: int = 4000) -> List[FlightPrice]:
        """Search flights using an existing page (page reuse mode for fast collection).
        
        This avoids the overhead of creating/closing a page for each search.
        The caller is responsible for page lifecycle.
        
        Args:
            page: Existing Playwright page to reuse
            query: Search query parameters
            page_timeout_ms: Page load timeout in ms (fast mode: 10000)
            wait_after_load_ms: Wait time after page load in ms (fast mode: 2000)
        """
        city = CITY_TO_CTRIP_ID.get(query.departure)
        city2 = CITY_TO_CTRIP_ID.get(query.destination)
        if not city or not city2:
            return []
        dep_code, _ = city
        arr_code, _ = city2
        try:
            return await self._do_search(page, query, dep_code, arr_code,
                                         page_timeout_ms=page_timeout_ms,
                                         wait_after_load_ms=wait_after_load_ms)
        except Exception as e:
            logger.warning(f"CtripBrowserSource with_page: {e}")
            return []

    async def _do_search(self, page, query, dep_code: str, arr_code: str,
                         page_timeout_ms: int = 20000, wait_after_load_ms: int = 4000) -> List[FlightPrice]:
        flight_data_map: Dict[str, FlightPrice] = {}
        api_intercepted = False
        seen: Set[str] = set()
        # 匹配手机端和电脑端的 API 端点
        api_patterns = (
            "flightListSearchForH5", "flightGloryList",  # 移动端
            "flightListSearch", "api/flightlist",        # 电脑端
            "getFlightList", "searchFlight",             # 其他可能
        )

        async def on_response(response):
            nonlocal api_intercepted
            url = response.url
            if response.status != 200:
                return
            for pat in api_patterns:
                if pat in url:
                    try:
                        data = await response.json()
                        # 尝试多种数据格式
                        items = data.get("fltitem") or data.get("finfo") or []
                        if not items and isinstance(data.get("data"), dict):
                            items = data["data"].get("flightList", [])
                        if not items:
                            items = data.get("flightList", [])
                        if isinstance(items, list):
                            for item in items:
                                entry = self._extract_flight(
                                    item, dep_code, arr_code, query, seen, page.url)
                                if entry:
                                    api_intercepted = True
                                    key = f"{entry.flight_no}_{entry.departure_time}"
                                    if key not in flight_data_map or entry.price < flight_data_map[key].price:
                                        flight_data_map[key] = entry
                    except Exception as e:
                        logger.debug(f"Ctrip parse: {e}")
                    break

        page.on("response", on_response)
        try:
            # 手机端搜索（电脑端会被 WhaleGuard 拦截）
            search_url = (
                f"https://m.ctrip.com/html5/flight/swift/list"
                f"?dcity={quote(query.departure)}&acity={quote(query.destination)}"
                f"&ddate={query.departure_date}&cabin=Y_S"
                f"&adult=1&child=0&infant=0"
            )
            await page.goto(search_url, wait_until="domcontentloaded", timeout=page_timeout_ms)
            await page.wait_for_timeout(wait_after_load_ms)

            # 滚动加载更多
            last_height = await page.evaluate("document.body.scrollHeight")
            for _ in range(SCROLL_PASSES):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    await page.wait_for_response(
                        lambda r: "flightListSearch" in r.url and r.status == 200,
                        timeout=2000,
                    )
                except Exception:
                    await page.wait_for_timeout(1000)
                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
        finally:
            page.remove_listener("response", on_response)

        # DOM fallback — 适配电脑网页版结构
        if not flight_data_map:
            try:
                html = await page.content()
                # 电脑网页版价格模式: 航班号 + 航司 + ¥价格
                patterns = [
                    # 模式1: 航班号(CA1234) + 航司 + ¥价格
                    re.compile(
                        r'([A-Z]{2}\d{2,4})[\s\S]{0,200}?'
                        r'([\u4e00-\u9fff]{2,8}(?:航空|国际|航司)?)[\s\S]{0,100}?'
                        r'[¥￥]\s*(\d{3,6})',
                        re.UNICODE,
                    ),
                    # 模式2: 航班号单独出现 + 价格
                    re.compile(
                        r'data-flightno="([A-Z]{2}\d{2,4})"[\s\S]{0,300}?'
                        r'(\d{3,6})\s*元',
                        re.UNICODE,
                    ),
                ]
                dom_count = 0
                for pattern in patterns:
                    if dom_count >= 30:
                        break
                    for m in pattern.finditer(html):
                        if dom_count >= 30:
                            break
                        fn_key = m.group(1)
                        if fn_key in seen:
                            continue
                        seen.add(fn_key)
                        try:
                            price = float(m.group(3) if m.lastindex >= 3 else m.group(2))
                            if price < 100:
                                continue
                            airline = m.group(2) if m.lastindex >= 3 else "未知航司"
                            entry = FlightPrice(
                                query_id=query.id or 0, airline=airline,
                                flight_no=fn_key, aircraft="",
                                departure_time="", arrival_time="",
                                departure_airport=query.departure,
                                arrival_airport=query.destination,
                                duration="", stops=0, price=price,
                                cabin_class=query.cabin_class or "economy",
                                source=self.name, recorded_at=datetime.now().isoformat(),
                                purchase_url=page.url,
                                sub_class="", seat_inventory=9, is_mock=False,
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
                        except (ValueError, IndexError):
                            continue
            except Exception as e:
                logger.debug(f"DOM fallback error: {e}")

        results = list(flight_data_map.values())
        if results or api_intercepted:
            logger.info(f"Ctrip: {len(results)} flights (api={'yes' if api_intercepted else 'no'})")
        return results

    # ── Flight extraction (sync, pure data parsing) ──────────────

    def _extract_flight(self, item: dict, default_dep: str, default_arr: str,
                        query: SearchQuery, seen: Set[str],
                        purchase_url: str = "") -> Optional[FlightPrice]:
        if not isinstance(item, dict):
            return None

        flight_no = airline_name = dep_airport = arr_airport = ""
        dep_time = arr_time = aircraft = duration = ""
        stops = 0
        lowest_price = 0.0
        sub_class = ""
        seat_inventory = 9

        # Format 1: flightListSearchForH5
        mutilstn = item.get("mutilstn", [])
        if mutilstn and isinstance(mutilstn, list):
            seg = mutilstn[0]
            if isinstance(seg, dict):
                basinfo = seg.get("basinfo") or {}
                dportinfo = seg.get("dportinfo") or {}
                aportinfo = seg.get("aportinfo") or {}
                dateinfo = seg.get("dateinfo") or {}
                craftinfo = seg.get("craftinfo") or {}

                flight_no = basinfo.get("flgno", "")
                airline_name = basinfo.get("airlineName") or basinfo.get("aircode", "")
                dep_airport = dportinfo.get("bsname") or dportinfo.get("aport") or default_dep
                arr_airport = aportinfo.get("bsname") or aportinfo.get("aport") or default_arr

                dt_raw = dateinfo.get("ddate", "") or ""
                at_raw = dateinfo.get("adate", "") or ""
                # Support both "YYYY-MM-DD HH:MM:SS" and ISO "YYYY-MM-DDTHH:MM:SS" formats
                def _extract_time(raw):
                    if not raw:
                        return ""
                    for sep in (" ", "T"):
                        if sep in raw:
                            return raw.split(sep)[1][:5]
                    return raw
                dep_time = _extract_time(dt_raw)
                arr_time = _extract_time(at_raw)
                aircraft = craftinfo.get("cdisname", "")
                stops = int(dateinfo.get("dcnt", 0))

                dur_raw = seg.get("duration") or seg.get("durationMin") or dateinfo.get("duration") or 0
                if dur_raw and float(dur_raw) > 0:
                    dmin = int(float(dur_raw))
                    duration = f"{dmin // 60}h{dmin % 60}m"

                best_policy = {}
                for pol in item.get("policyinfo", []):
                    pv = pol.get("tprice", 0)
                    if pv and float(pv) > 0:
                        if lowest_price == 0.0 or float(pv) < lowest_price:
                            lowest_price = float(pv)
                            best_policy = pol
                if best_policy:
                    sub_class = (best_policy.get("class") or best_policy.get("cabin") or "").strip()
                    qty_s = str(best_policy.get("qty", "9"))
                    try:
                        seat_inventory = int(qty_s) if qty_s.isdigit() else 9
                    except ValueError:
                        seat_inventory = 9
                # Fallback sub_class scan
                for pol in item.get("policyinfo", []):
                    if not sub_class:
                        sub_class = (pol.get("class") or pol.get("cabin") or "").strip()
                    if seat_inventory == 9:
                        try:
                            seat_inventory = int(str(pol.get("qty", "9")))
                        except (ValueError, TypeError):
                            pass

        # Format 2: flightGloryList
        elif "departureTime" in item or "arrivalTime" in item:
            flight_no = item.get("flightNo", "")
            airline_name = item.get("airlineName", "")
            lowest_price = float(item.get("lowestPrice") or item.get("price", 0))
            dep_airport = item.get("departureAirportName") or item.get("departureCityCode") or default_dep
            arr_airport = item.get("arrivalAirportName") or item.get("arrivalCityCode") or default_arr
            for raw, field in [("departureTime", "dep"), ("arrivalTime", "arr")]:
                rv = item.get(raw, "") or ""
                for sep in (" ", "T"):
                    if sep in rv:
                        rv = rv.split(sep)[-1][:5]
                        break
                if field == "dep":
                    dep_time = rv
                else:
                    arr_time = rv
            aircraft = item.get("aircraftName", "")
            dur_raw = item.get("flightDuration") or item.get("durationMin") or 0
            if dur_raw and float(dur_raw) > 0:
                dmin = int(float(dur_raw))
                duration = f"{dmin // 60}h{dmin % 60}m"
            # Subclass from top-level
            sub_class = (item.get("cabin") or item.get("cabinClass") or item.get("class") or "").strip()

        # Format 3/4: Calendar / Generic
        elif ("airlineName" in item or "flightNo" in item) and ("price" in item or "lowestPrice" in item):
            airline_name = item.get("airlineName", "")
            flight_no = item.get("flightNo", "")
            lowest_price = float(item.get("price") or item.get("lowestPrice", 0))
            dep_airport = item.get("departureCityCode", default_dep)
            arr_airport = item.get("arrivalCityCode", default_arr)
            dep_time = item.get("departureTime", "") or item.get("dtime", "") or ""
            arr_time = item.get("arrivalTime", "") or item.get("atime", "") or ""

        # Validation
        if not lowest_price or lowest_price <= 0 or not flight_no:
            return None
        if not airline_name:
            airline_name = "未知航司"
        if flight_no in seen:
            return None
        seen.add(flight_no)

        # Schedule backfill
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

        if not duration and dep_time and arr_time:
            try:
                def _to_min(t):
                    t = t.strip().replace(":", "")
                    return int(t[:2]) * 60 + int(t[2:4]) if len(t) >= 4 else 0
                dm = _to_min(dep_time)
                am = _to_min(arr_time)
                if dm and am:
                    diff = am - dm
                    if diff < 0:
                        diff += 24 * 60
                    h, m = divmod(diff, 60)
                    duration = f"{h}h{m}m"
            except Exception:
                pass

        return FlightPrice(
            query_id=query.id or 0,
            airline=airline_name, flight_no=flight_no, aircraft=aircraft,
            departure_time=dep_time, arrival_time=arr_time,
            departure_airport=dep_airport, arrival_airport=arr_airport,
            duration=duration, stops=stops, price=lowest_price,
            cabin_class=query.cabin_class or "economy",
            source=self.name, recorded_at=datetime.now().isoformat(),
            purchase_url=purchase_url,
            sub_class=sub_class, seat_inventory=seat_inventory, is_mock=False,
        )
