"""
Flight Monitor - Data Aggregator Service
Handles O(N) high-performance grouping, deduplication, and cross-platform price synthesis.
"""
from collections import defaultdict
from typing import List, Dict, Any
from core.models import FlightPrice, SearchQuery
from datasources.flight_schedules import lookup_flight_schedule, get_aircraft_for_flight
from datasources.mock_source import is_international_route
from config import PURCHASE_PLATFORMS
import logging

logger = logging.getLogger(__name__)

# Enhanced aircraft details database
AIRCRAFT_DETAILS = {
    "空客 320": {"type": "窄体客机", "manufacturer": "Airbus", "labels": ["常见窄体"]},
    "空客 321": {"type": "窄体客机", "manufacturer": "Airbus", "labels": ["加长窄体", "较高舒适度"]},
    "空客 319": {"type": "窄体客机", "manufacturer": "Airbus", "labels": ["紧凑窄体"]},
    "空客 330": {"type": "宽体客机", "manufacturer": "Airbus", "labels": ["舒适宽体", "双通道"]},
    "空客 350": {"type": "宽体客机", "manufacturer": "Airbus", "labels": ["旗舰宽体", "降噪客舱"]},
    "空客 380": {"type": "宽体客机", "manufacturer": "Airbus", "labels": ["巨无霸", "双层客舱"]},
    "波音 737": {"type": "窄体客机", "manufacturer": "Boeing", "labels": ["常见窄体"]},
    "波音 738": {"type": "窄体客机", "manufacturer": "Boeing", "labels": ["常见窄体"]},
    "波音 777": {"type": "宽体客机", "manufacturer": "Boeing", "labels": ["大型宽体", "越洋主力"]},
    "波音 787": {"type": "宽体客机", "manufacturer": "Boeing", "labels": ["梦想客机", "高压氧舱"]},
    "波音 747": {"type": "宽体客机", "manufacturer": "Boeing", "labels": ["空中女王", "四发巨无霸"]},
    "C919":  {"type": "窄体客机", "manufacturer": "COMAC", "labels": ["国产大飞机", "全新体验"]},
    "ARJ21": {"type": "支线客机", "manufacturer": "COMAC", "labels": ["国产支线", "小巧灵活"]},
    "CRJ-900": {"type": "支线客机", "manufacturer": "Bombardier", "labels": ["小巧支线"]},
    "ERJ":   {"type": "支线客机", "manufacturer": "Embraer", "labels": ["巴西支线"]},
    "E190":  {"type": "支线客机", "manufacturer": "Embraer", "labels": ["巴航工业"]},
    "E195":  {"type": "支线客机", "manufacturer": "Embraer", "labels": ["巴航工业"]},
}

# Alias mapping for fuzzy match
_AIRCRAFT_ALIASES = {
    "a320": "空客 320", "a321": "空客 321", "a319": "空客 319",
    "a330": "空客 330", "a350": "空客 350", "a380": "空客 380",
    "airbus": "空客 320",
    "b737": "波音 737", "b738": "波音 738", "b777": "波音 777",
    "b787": "波音 787", "b747": "波音 747", "b73": "波音 737",
    "boeing": "波音 737",
    "comac": "C919", "c919": "C919",
    "arj": "ARJ21", "arj21": "ARJ21",
    "crj": "CRJ-900", "crj9": "CRJ-900",
    "e190": "E190", "e195": "E195", "erj": "E190",
    "巴航": "E190", "embraer": "E190",
}

# Platform lists per route type
DOM_PLATFORMS = ["ctrip", "qunar", "fliggy", "tongcheng",
                 "spring", "juneyao", "airchina", "csair", "ceair", "hainan"]
INTL_PLATFORMS = ["tripcom", "skyscanner", "googleflights", "kayak", "expedia"]


class FlightAggregator:
    @staticmethod
    def _calc_duration(dep_time: str, arr_time: str) -> str:
        """Calculate flight duration from HH:MM times. Handles overnight flights."""
        try:
            def _to_minutes(t: str) -> int:
                t = t.strip().replace(":", "")
                if len(t) >= 4:
                    return int(t[:2]) * 60 + int(t[2:4])
                return 0
            dep_m = _to_minutes(dep_time)
            arr_m = _to_minutes(arr_time)
            if not dep_m or not arr_m:
                return ""
            diff = arr_m - dep_m
            if diff < 0:
                diff += 24 * 60  # overnight
            hours, minutes = divmod(diff, 60)
            return f"{hours}h{minutes}m"
        except Exception:
            return ""

    @staticmethod
    def _sanitize_airport(raw_airport: str, default: str) -> str:
        """Replace city codes with readable airport names when possible."""
        if not raw_airport:
            return default
        # Don't show raw city codes like "BJS", "SHA"
        if len(raw_airport) == 3 and raw_airport.isupper() and raw_airport.isalpha():
            # Map common city codes to Chinese names
            code_map = {
                "BJS": "北京", "SHA": "上海", "CAN": "广州", "SZX": "深圳",
                "CTU": "成都", "HGH": "杭州", "WUH": "武汉", "XIY": "西安",
                "CKG": "重庆", "TAO": "青岛", "CSX": "长沙", "NKG": "南京",
                "XMN": "厦门", "KMG": "昆明", "DLC": "大连", "TSN": "天津",
                "SYX": "三亚", "HAK": "海口", "HRB": "哈尔滨", "SHE": "沈阳",
                "LJG": "丽江", "KWL": "桂林", "HKG": "香港", "MFM": "澳门",
                "TPE": "台北", "TYO": "东京", "OSA": "大阪", "SEL": "首尔",
                "BKK": "曼谷", "SIN": "新加坡", "KUL": "吉隆坡",
            }
            return code_map.get(raw_airport, raw_airport)
        return raw_airport
    @staticmethod
    def _get_platform_keys(departure: str, destination: str) -> list:
        """Determine route type and return target platform keys."""
        try:
            intl = is_international_route(departure, destination)
        except Exception:
            intl = False
        return INTL_PLATFORMS if intl else DOM_PLATFORMS

    @staticmethod
    def _backfill_flight_data(flight: FlightPrice) -> None:
        """Backfill missing flight data from schedule lookup."""
        if not flight.departure_time:
            sched = lookup_flight_schedule(flight.flight_no)
            if sched:
                flight.departure_time = sched["dep"]
                flight.arrival_time = sched["arr"]
                flight.duration = f"{sched['duration_min'] // 60}h{sched['duration_min'] % 60}m"
                flight.aircraft = flight.aircraft or sched.get("aircraft", "")
            else:
                flight.aircraft = flight.aircraft or get_aircraft_for_flight(flight.flight_no)
        if not flight.duration and flight.departure_time and flight.arrival_time:
            flight.duration = FlightAggregator._calc_duration(flight.departure_time, flight.arrival_time)

    @staticmethod
    def _generate_estimated_prices(real_flights: list, mock_flights: list,
                                    seen_platforms: dict, plat_keys: list,
                                    query: SearchQuery) -> list:
        """Generate estimated cross-platform prices for missing platforms."""
        _platform_offset = {
            "qunar": 0.94, "fliggy": 0.96, "tongcheng": 0.97,
            "tripcom": 0.95, "skyscanner": 0.93, "googleflights": 0.98,
            "kayak": 0.96, "expedia": 1.02,
            "spring": 0.88, "juneyao": 0.90, "airchina": 1.0,
            "csair": 0.97, "ceair": 0.98, "hainan": 1.01,
        }
        extra_prices = []
        for p in real_flights:
            fn_key = (p.airline, p.flight_no)
            missing = set(plat_keys) - seen_platforms[fn_key]
            for pk in missing:
                factor = _platform_offset.get(pk, 0.97)
                plat_price = max(50, round(p.price * factor / 10) * 10)
                pi = PURCHASE_PLATFORMS.get(pk, {})
                url = ""
                tmpl = pi.get("url", "")
                if tmpl:
                    try:
                        url = tmpl.format(dep=query.departure, arr=query.destination,
                                         date=query.departure_date, dep_code="", arr_code="")
                    except Exception:
                        url = tmpl
                extra_prices.append(FlightPrice(
                    query_id=p.query_id, airline=p.airline, flight_no=p.flight_no,
                    aircraft=p.aircraft, departure_time=p.departure_time,
                    arrival_time=p.arrival_time, departure_airport=p.departure_airport,
                    arrival_airport=p.arrival_airport, duration=p.duration, stops=p.stops,
                    price=plat_price, cabin_class=p.cabin_class,
                    source=pk, recorded_at=p.recorded_at, purchase_url=url,
                    is_mock=True, sub_class=p.sub_class, seat_inventory=p.seat_inventory,
                ))
        return extra_prices

    @staticmethod
    def _group_and_aggregate(all_prices: list, real_flights: list, mock_flights: list) -> tuple:
        """O(N) hash grouping with depth aggregation. Returns (grouped_flights, min_price, all_platforms).

        Groups by (airline, flight_no) only — not departure_time.  This prevents
        fragmenting the same flight into multiple groups when different sources
        return different or empty departure_time values.
        """
        _real_sources: Dict[tuple, set] = defaultdict(set)
        for p in real_flights:
            _real_sources[(p.airline, p.flight_no)].add(p.source)
        for p in mock_flights:
            fn_key = (p.airline, p.flight_no)
            if fn_key in _real_sources:
                _real_sources[fn_key].add(p.source)

        grouped = {}
        min_price = float('inf')
        platforms = set()

        for p in all_prices:
            key = (p.airline, p.flight_no)
            min_price = min(min_price, p.price)
            platforms.add(p.source)

            if key not in grouped:
                grouped[key] = {
                    "airline": p.airline, "flight_no": p.flight_no,
                    "aircraft": p.aircraft or "未知机型",
                    "aircraft_details": FlightAggregator._get_aircraft_details(p.aircraft or "未知机型"),
                    "departure_time": p.departure_time or "时间待定",
                    "arrival_time": p.arrival_time or "待定",
                    "departure_airport": FlightAggregator._sanitize_airport(p.departure_airport, "") or p.departure_airport,
                    "arrival_airport": FlightAggregator._sanitize_airport(p.arrival_airport, "") or p.arrival_airport,
                    "duration": p.duration or "—", "stops": p.stops,
                    "price": p.price, "purchase_url": p.purchase_url,
                    "source": p.source, "platform_prices": {},
                }
            else:
                # Merge: prefer the entry with the most complete time info
                existing = grouped[key]
                if p.departure_time and existing.get("departure_time") in ("时间待定", "", None):
                    # Upgrade from "时间待定" to actual time
                    existing["departure_time"] = p.departure_time
                    if p.arrival_time:
                        existing["arrival_time"] = p.arrival_time
                    if p.duration:
                        existing["duration"] = p.duration
                    if p.aircraft and existing.get("aircraft") in ("未知机型", ""):
                        existing["aircraft"] = p.aircraft
                        existing["aircraft_details"] = FlightAggregator._get_aircraft_details(p.aircraft)
                    if p.departure_airport:
                        existing["departure_airport"] = p.departure_airport
                    if p.arrival_airport:
                        existing["arrival_airport"] = p.arrival_airport

            if p.price < grouped[key]["price"]:
                grouped[key]["price"] = p.price
                grouped[key]["purchase_url"] = p.purchase_url
                grouped[key]["source"] = p.source

            real_set = _real_sources.get(key, set())
            is_estimated = p.source not in real_set
            pp = grouped[key]["platform_prices"]
            if p.source not in pp or p.price < pp[p.source]["price"]:
                pi = PURCHASE_PLATFORMS.get(p.source, {})
                name = pi.get("name", p.source)
                pp[p.source] = {
                    "source": p.source, "price": p.price,
                    "purchase_url": p.purchase_url,
                    "platform_name": f"{name} [预估]" if is_estimated else name,
                    "platform_icon": pi.get("icon", ""),
                    "platform_color": pi.get("color", "#666"),
                    "estimated": is_estimated,
                }
        return grouped, min_price, platforms

    @staticmethod
    def _dedup_and_sort(grouped: dict) -> list:
        """Sort grouped flights by price. Grouping already unique by (airline, flight_no)."""
        final = []
        for flight in grouped.values():
            plat_list = sorted(flight["platform_prices"].values(), key=lambda x: x["price"])
            flight["platform_prices"] = plat_list[:8]
            final.append(flight)
        final.sort(key=lambda x: x["price"])
        return final

    @staticmethod
    def process_search_results(query: SearchQuery, raw_prices: List[FlightPrice]) -> Dict[str, Any]:
        """O(N) Optimized processing of raw flight prices."""
        if not raw_prices:
            return {"count": 0, "total_records": 0, "min_price": 0,
                    "platforms": [], "flights": []}

        plat_keys = FlightAggregator._get_platform_keys(query.departure, query.destination)

        # Separate real data from mock data
        # Real: any actual crawler source (ctrip_browser, ctrip, multi-platform, etc.)
        # Mock: only the mock source generates synthetic data
        real_flights = [p for p in raw_prices if p.source != "mock"]
        mock_flights = [p for p in raw_prices if p.source == "mock"]

        # Backfill flight data
        for p in real_flights:
            FlightAggregator._backfill_flight_data(p)
        for p in mock_flights:
            FlightAggregator._backfill_flight_data(p)
            p.aircraft = p.aircraft or get_aircraft_for_flight(p.flight_no)

        # Aggregate all platforms from real data
        seen_platforms = defaultdict(set)
        real_by_flightno = defaultdict(list)
        for p in real_flights:
            fn_key = (p.airline, p.flight_no)
            real_by_flightno[fn_key].append(p)
            seen_platforms[fn_key].add(p.source)

        # Keep mock that match real flight numbers (cross-platform comparison)
        matched_mock = []
        for p in mock_flights:
            fn_key = (p.airline, p.flight_no)
            if fn_key in real_by_flightno:
                matched_mock.append(p)
                seen_platforms[fn_key].add(p.source)

        all_prices = real_flights + matched_mock
        extra = FlightAggregator._generate_estimated_prices(
            real_flights, matched_mock, seen_platforms, plat_keys, query)
        all_prices.extend(extra)

        grouped, min_price, platforms = FlightAggregator._group_and_aggregate(
            all_prices, real_flights, mock_flights)
        final_list = FlightAggregator._dedup_and_sort(grouped)

        return {
            "count": len(final_list),
            "total_records": len(all_prices),
            "min_price": min_price if min_price != float('inf') else 0,
            "platforms": list(platforms),
            "flights": final_list[:30],
        }

    @staticmethod
    def _get_aircraft_details(aircraft_name: str) -> Dict[str, Any]:
        """Fuzzy match aircraft details via keywords and aliases."""
        if not aircraft_name:
            return {"type": "常规客机", "manufacturer": "Other", "labels": []}
        name_lower = aircraft_name.lower()
        # Try exact/substring match in main dict
        for key, details in AIRCRAFT_DETAILS.items():
            if key.lower() in name_lower:
                return details
        # Try alias match
        for alias, target in _AIRCRAFT_ALIASES.items():
            if alias in name_lower:
                return AIRCRAFT_DETAILS.get(target, {"type": "常规客机", "manufacturer": "Other", "labels": []})
        return {"type": "常规客机", "manufacturer": "Other", "labels": []}
