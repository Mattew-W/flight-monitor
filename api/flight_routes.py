"""
Flight Monitor API — Flight Routes
"""
import logging
from datetime import datetime
from flask import request, jsonify
from api._shared import rate_limiter, client_ip

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────

AIRLINE_BASES = {
    "CA": ("北京", "PEK"), "MU": ("上海", "SHA"), "CZ": ("广州", "CAN"),
    "HU": ("海口", "HAK"), "ZH": ("深圳", "SZX"), "MF": ("厦门", "XMN"),
    "3U": ("成都", "CTU"), "9C": ("上海", "SHA"), "HO": ("上海", "SHA"),
    "SC": ("济南", "TNA"), "FM": ("上海", "SHA"), "KN": ("北京", "PKX"),
    "JD": ("北京", "PEK"), "GS": ("天津", "TSN"), "G5": ("贵阳", "KWE"),
    "EU": ("成都", "CTU"), "GJ": ("杭州", "HGH"),
    "AQ": ("泉州", "JJN"), "DR": ("珠海", "ZUH"), "DZ": ("海口", "HAK"),
    "GX": ("南宁", "NNG"), "GT": ("海口", "HAK"), "NS": ("福州", "FOC"),
    "PN": ("深圳", "SZX"), "QW": ("青岛", "TAO"), "RY": ("昆明", "KMG"),
    "TV": ("昆明", "KMG"), "UQ": ("乌鲁木齐", "URC"), "Y8": ("深圳", "SZX"),
}

AIRLINE_MAP = {
    "CA": "中国国航", "MU": "东方航空", "CZ": "南方航空",
    "HU": "海南航空", "ZH": "深圳航空", "MF": "厦门航空",
    "3U": "四川航空", "9C": "春秋航空", "HO": "吉祥航空",
    "FM": "上海航空", "SC": "山东航空",
}

COMMON_TRUNK_DESTINATIONS = {
    "北京": ["上海", "广州", "深圳", "成都", "西安", "杭州", "南京", "厦门", "武汉", "长沙", "重庆", "昆明"],
    "上海": ["北京", "广州", "深圳", "成都", "西安", "厦门", "三亚", "桂林", "昆明", "重庆", "贵阳"],
    "广州": ["北京", "上海", "成都", "杭州", "南京", "海口", "三亚", "昆明", "西安", "厦门", "重庆"],
    "成都": ["北京", "上海", "广州", "深圳", "拉萨", "昆明", "西安", "杭州", "南京"],
    "深圳": ["北京", "上海", "成都", "杭州", "南京", "西安", "昆明", "重庆"],
    "厦门": ["北京", "上海", "广州", "深圳", "成都", "杭州"],
    "海口": ["北京", "上海", "广州", "深圳", "成都", "三亚"],
    "济南": ["北京", "上海", "广州", "深圳", "成都", "厦门"],
    "杭州": ["北京", "广州", "深圳", "成都", "西安", "昆明"],
    "贵阳": ["北京", "上海", "广州", "深圳"],
    "天津": ["上海", "广州", "深圳", "成都", "西安"],
}


def _get_airline_base(flight_no: str) -> tuple | None:
    prefix = flight_no[:2].upper() if len(flight_no) >= 2 else ""
    return AIRLINE_BASES.get(prefix)


def _infer_flight_route(flight_no: str, sched: dict) -> dict | None:
    base_info = _get_airline_base(flight_no)
    if not base_info:
        return None
    base_city, base_airport = base_info
    dep_city = sched.get("dep_city", "")
    arr_city = sched.get("arr_city", "")
    dep_airport = sched.get("dep_airport", "")
    arr_airport = sched.get("arr_airport", "")
    if dep_city and arr_city:
        return None
    known_city = dep_city or arr_city
    if known_city:
        return None
    if not dep_city and not arr_city:
        common_dests = COMMON_TRUNK_DESTINATIONS.get(base_city, ["北京"])
        dest = common_dests[0] if common_dests else "北京"
        try:
            from config import get_config
            cfg = get_config()
            dest_airport = cfg.city_codes.get(dest, "")
        except Exception:
            dest_airport = ""
        return {
            "dep_city": base_city,
            "arr_city": dest,
            "dep_airport": dep_airport or base_airport,
            "arr_airport": arr_airport or dest_airport,
        }
    return None


# ── Route Registration ───────────────────────────────────────

def register(app, db, monitor):
    """Register all flight-related routes."""

    @app.route("/api/flight/<flight_no>", methods=["GET"])
    def flight_lookup(flight_no):
        try:
            from core.services import FlightScheduleService
        except ImportError:
            return jsonify({"found": False, "error": "schedule db not available"}), 501
        sched_raw = FlightScheduleService.lookup(flight_no.upper())
        sched = dict(sched_raw) if sched_raw else None
        if sched:
            sched["flight_no"] = flight_no.upper()
            dep_city = sched.get("dep_city", "")
            arr_city = sched.get("arr_city", "")
            if not dep_city or not arr_city:
                inferred = _infer_flight_route(flight_no, sched)
                if inferred:
                    sched["dep_city"] = inferred.get("dep_city", dep_city)
                    sched["arr_city"] = inferred.get("arr_city", arr_city)
                    sched["dep_airport"] = sched.get("dep_airport") or inferred.get("dep_airport", "")
                    sched["arr_airport"] = sched.get("arr_airport") or inferred.get("arr_airport", "")
            if sched.get("dep_city") and sched.get("arr_city"):
                sched["found"] = True
                try:
                    from core.services import BingService
                    BingService().clear_negative_cache(flight_no)
                except Exception:
                    pass
                return jsonify(sched)
        base = _get_airline_base(flight_no)
        prefix = flight_no[:2].upper() if len(flight_no) >= 2 else ""
        airline_name = AIRLINE_MAP.get(prefix, prefix)
        return jsonify({
            "found": False,
            "flight_no": flight_no.upper(),
            "airline": airline_name,
            "dep_city_hint": base[0] if base else "",
            "dep_airport_hint": base[1] if base else "",
        })

    @app.route("/api/flight/search", methods=["GET"])
    def flight_search():
        try:
            from core.services import FlightScheduleService
        except ImportError:
            return jsonify({"error": "schedule db not available"}), 501
        dep = request.args.get("dep", "")
        arr = request.args.get("arr", "")
        if not dep or not arr:
            return jsonify({"error": "dep and arr are required"}), 400
        results = FlightScheduleService.search_by_route(dep, arr)
        return jsonify({"results": results, "count": len(results)})

    @app.route("/api/flight/live", methods=["GET"])
    def flight_live_price():
        if not rate_limiter.allow(client_ip(), max_calls=20, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429
        import requests as req
        dep = request.args.get("dep", "").upper()
        arr = request.args.get("arr", "").upper()
        date_str = request.args.get("date", "")
        cabin = request.args.get("cabin", "economy")
        if not dep or not arr or not date_str:
            return jsonify({"error": "missing params: dep, arr, date"}), 400
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        if len(dep) > 3 or not dep.isalpha():
            try:
                from config import get_config
                dep = get_config().city_codes.get(dep, dep)
            except Exception:
                pass
        if len(arr) > 3 or not arr.isalpha():
            try:
                from config import get_config
                arr = get_config().city_codes.get(arr, arr)
            except Exception:
                pass
        cabin_map = {"economy": "Y_S", "business": "C_S", "first": "F_S"}
        cabin_param = cabin_map.get(cabin, "Y_S")
        url = "https://m.ctrip.com/restapi/soa2/14666/json/getLowestPriceCalendar"
        try:
            resp = req.get(
                url,
                params={
                    "DepartCityCode": dep,
                    "ArriveCityCode": arr,
                    "StartDate": date_str,
                    "EndDate": date_str,
                    "cabin": cabin_param,
                    "adult": 1,
                    "child": 0,
                    "infant": 0,
                },
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                        "Mobile/15E148 Safari/604.1"
                    ),
                    "Accept": "application/json",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                price = None
                items = data.get("LowestPriceCalendarItems") or data.get("Items") or data.get("data") or []
                if items and len(items) > 0:
                    for item in items:
                        if item.get("Date") == date_str or item.get("DepartDate") == date_str:
                            price = item.get("LowestPrice") or item.get("Price") or item.get("price")
                            break
                    if price is None and items[0]:
                        price = items[0].get("LowestPrice") or items[0].get("Price") or items[0].get("price")
                if price:
                    return jsonify({
                        "found": True,
                        "dep": dep, "arr": arr, "date": date_str, "cabin": cabin,
                        "price": float(price),
                        "source": "ctrip_calendar",
                    })
            return jsonify({
                "found": False,
                "dep": dep, "arr": arr, "date": date_str,
                "error": f"HTTP {resp.status_code}",
            })
        except Exception as e:
            logger.warning(f"flight_live_price failed: {type(e).__name__}")
            return jsonify({"found": False, "error": "external API call failed"}), 502

    @app.route("/api/flight/bing", methods=["GET"])
    def flight_bing_search():
        dep = request.args.get("dep", "")
        arr = request.args.get("arr", "")
        date_str = request.args.get("date", "")
        cabin = request.args.get("cabin", "economy")
        if not dep or not arr or not date_str:
            return jsonify({"error": "missing params: dep, arr, date"}), 400
        try:
            from core.services import BingService
            from core.models import SearchQuery
            bing = BingService()
            if not bing.is_available():
                return jsonify({"error": "bing search not available (requests lib missing)"}), 501
            q = SearchQuery(
                departure=dep,
                destination=arr,
                departure_date=date_str,
                cabin_class=cabin,
            )
            flights = bing.search_flights(q)
            if flights:
                return jsonify({
                    "found": True,
                    "dep": dep, "arr": arr, "date": date_str, "cabin": cabin,
                    "count": len(flights),
                    "min_price": min(f.price for f in flights),
                    "max_price": max(f.price for f in flights),
                    "flights": [
                        {
                            "airline": f.airline,
                            "flight_no": f.flight_no,
                            "price": f.price,
                            "departure_airport": f.departure_airport,
                            "arrival_airport": f.arrival_airport,
                            "purchase_url": f.purchase_url,
                        }
                        for f in flights[:20]
                    ],
                })
            return jsonify({"found": False, "error": "no flights found"}), 404
        except Exception as e:
            logger.warning(f"flight_bing_search failed: {type(e).__name__}")
            return jsonify({"found": False, "error": "bing search failed"}), 502

    @app.route("/api/flight/bing_route", methods=["GET"])
    def flight_bing_route_lookup():
        flight_no = request.args.get("flight_no", "").strip()
        if not flight_no:
            return jsonify({"found": False, "error": "missing flight_no"}), 400
        if not rate_limiter.allow(client_ip(), max_calls=10, window_s=60):
            return jsonify({"error": "rate limit exceeded"}), 429
        try:
            from core.services import BingService
            bing = BingService()
            if not bing.is_available():
                return jsonify({"found": False, "error": "bing not available"}), 503
            route_info = bing.lookup_route(flight_no)
            if route_info:
                route_info["found"] = True
                route_info["flight_no"] = flight_no.upper()
                return jsonify(route_info)
            return jsonify({"found": False, "flight_no": flight_no.upper()})
        except Exception as e:
            logger.warning(f"flight_bing_route failed: {type(e).__name__}: {e}")
            return jsonify({"found": False, "error": "route lookup failed"}), 502
