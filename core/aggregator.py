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
    def process_search_results(query: SearchQuery, raw_prices: List[FlightPrice]) -> Dict[str, Any]:
        """O(N) Optimized processing of raw flight prices."""
        if not raw_prices:
            return {"count": 0, "total_records": 0, "min_price": 0,
                    "platforms": [], "flights": []}

        # 1. Determine route type and target platforms
        intl = False
        try:
            intl = is_international_route(query.departure, query.destination)
        except Exception:
            pass
        plat_keys = INTL_PLATFORMS if intl else DOM_PLATFORMS

        # 2. Separate data sources
        real_flights = []
        mock_flights = []
        for p in raw_prices:
            if p.source == "ctrip_browser":
                real_flights.append(p)
            else:
                mock_flights.append(p)

        all_prices = []

        # 3. Core: O(N) processing
        if real_flights:
            # Build lookup key (airline, flight_no) for matching — NOT time-dependent
            real_by_flightno = defaultdict(list)
            seen_platforms = defaultdict(set)

            for p in real_flights:
                # Backfill missing data from schedule
                if not p.departure_time:
                    sched = lookup_flight_schedule(p.flight_no)
                    if sched:
                        p.departure_time = sched["dep"]
                        p.arrival_time = sched["arr"]
                        p.duration = f"{sched['duration_min'] // 60}h{sched['duration_min'] % 60}m"
                        p.aircraft = p.aircraft or sched.get("aircraft", "")
                    else:
                        p.aircraft = p.aircraft or get_aircraft_for_flight(p.flight_no)
                # Backfill duration from dep/arr times if still empty
                if not p.duration and p.departure_time and p.arrival_time:
                    p.duration = FlightAggregator._calc_duration(p.departure_time, p.arrival_time)

                fn_key = (p.airline, p.flight_no)
                real_by_flightno[fn_key].append(p)
                seen_platforms[fn_key].add(p.source)
                all_prices.append(p)

            # Keep only mock flights matching real flight numbers
            for p in mock_flights:
                fn_key = (p.airline, p.flight_no)
                if fn_key in real_by_flightno:
                    all_prices.append(p)
                    seen_platforms[fn_key].add(p.source)

            # Generate estimated cross-platform prices for missing platforms
            # Uses ctrip_browser real price as anchor with platform-specific offsets
            # Clearly marked as "estimated" to distinguish from real data
            extra_prices = []
            for p in real_flights:
                fn_key = (p.airline, p.flight_no)
                missing = set(plat_keys) - seen_platforms[fn_key]
                # Platform-specific price offsets relative to ctrip (based on market observation)
                _platform_offset = {
                    "qunar": 0.94, "fliggy": 0.96, "tongcheng": 0.97,
                    "tripcom": 0.95, "skyscanner": 0.93, "googleflights": 0.98,
                    "kayak": 0.96, "expedia": 1.02,
                    "spring": 0.88, "juneyao": 0.90, "airchina": 1.0,
                    "csair": 0.97, "ceair": 0.98, "hainan": 1.01,
                }
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
                        except (KeyError, Exception):
                            url = tmpl
                    extra_prices.append(FlightPrice(
                        query_id=p.query_id, airline=p.airline, flight_no=p.flight_no,
                        aircraft=p.aircraft, departure_time=p.departure_time,
                        arrival_time=p.arrival_time, departure_airport=p.departure_airport,
                        arrival_airport=p.arrival_airport, duration=p.duration, stops=p.stops,
                        price=plat_price, cabin_class=p.cabin_class,
                        source=pk,
                        recorded_at=p.recorded_at, purchase_url=url,
                    ))
            all_prices.extend(extra_prices)
        else:
            # Pure mock mode — also enrich with aircraft details
            for p in mock_flights:
                if not p.departure_time:
                    sched = lookup_flight_schedule(p.flight_no)
                    if sched:
                        p.departure_time = sched["dep"]
                        p.arrival_time = sched["arr"]
                        p.aircraft = p.aircraft or sched.get("aircraft", "")
                p.aircraft = p.aircraft or get_aircraft_for_flight(p.flight_no)
            all_prices = mock_flights

        # Track which platforms have real (non-estimated) prices per flight
        _real_sources_per_flight: Dict[tuple, set] = defaultdict(set)
        for p in real_flights:
            _real_sources_per_flight[(p.airline, p.flight_no, p.departure_time)].add(p.source)
        for p in mock_flights:
            fn_key = (p.airline, p.flight_no, p.departure_time)
            if fn_key in _real_sources_per_flight:
                _real_sources_per_flight[fn_key].add(p.source)

        # 4. Hash grouping with depth aggregation (O(N) single pass)
        grouped_flights = {}
        min_overall_price = float('inf')
        all_platforms = set()

        for p in all_prices:
            key = (p.airline, p.flight_no, p.departure_time)
            min_overall_price = min(min_overall_price, p.price)
            all_platforms.add(p.source)

            if key not in grouped_flights:
                ac_name = p.aircraft or "未知机型"
                dep_ap = FlightAggregator._sanitize_airport(p.departure_airport, "")
                arr_ap = FlightAggregator._sanitize_airport(p.arrival_airport, "")
                grouped_flights[key] = {
                    "airline": p.airline,
                    "flight_no": p.flight_no,
                    "aircraft": ac_name,
                    "aircraft_details": FlightAggregator._get_aircraft_details(ac_name),
                    "departure_time": p.departure_time or "时间待定",
                    "arrival_time": p.arrival_time or "待定",
                    "departure_airport": dep_ap or p.departure_airport,
                    "arrival_airport": arr_ap or p.arrival_airport,
                    "duration": p.duration or "—",
                    "stops": p.stops,
                    "price": p.price,
                    "purchase_url": p.purchase_url,
                    "source": p.source,
                    "platform_prices": {},
                }

            # Keep lowest price for flight card
            if p.price < grouped_flights[key]["price"]:
                grouped_flights[key]["price"] = p.price
                grouped_flights[key]["purchase_url"] = p.purchase_url
                grouped_flights[key]["source"] = p.source

            # Is this platform price real or estimated?
            real_set = _real_sources_per_flight.get(key, set())
            is_estimated = p.source not in real_set

            # Platform dedup: keep lowest per platform
            p_dict = grouped_flights[key]["platform_prices"]
            if p.source not in p_dict or p.price < p_dict[p.source]["price"]:
                pi = PURCHASE_PLATFORMS.get(p.source, {})
                name = pi.get("name", p.source)
                p_dict[p.source] = {
                    "source": p.source,
                    "price": p.price,
                    "purchase_url": p.purchase_url,
                    "platform_name": f"{name} [预估]" if is_estimated else name,
                    "platform_icon": pi.get("icon", ""),
                    "platform_color": pi.get("color", "#666"),
                    "estimated": is_estimated,
                }

        # 5. Build final sorted output with dedup by flight_no
        deduped = {}
        for flight in grouped_flights.values():
            mk = (flight["airline"], flight["flight_no"])
            if mk not in deduped:
                deduped[mk] = flight
            else:
                e = deduped[mk]
                # Keep the one with time data
                if flight.get("departure_time") and flight["departure_time"] not in ("时间待定",""):
                    if not e.get("departure_time") or e["departure_time"] in ("时间待定",""):
                        for attr in ("departure_time", "arrival_time", "aircraft",
                                     "duration", "departure_airport", "arrival_airport",
                                     "aircraft_details"):
                            if flight.get(attr):
                                e[attr] = flight[attr]
                # Merge platform prices
                sp = {x["source"] for x in e["platform_prices"].values()}
                for pf in flight["platform_prices"].values():
                    if pf["source"] not in sp:
                        e["platform_prices"][pf["source"]] = pf
                if flight["price"] < e["price"]:
                    e["price"] = flight["price"]

        final_list = []
        for flight in deduped.values():
            plat_list = sorted(flight["platform_prices"].values(), key=lambda x: x["price"])
            flight["platform_prices"] = plat_list[:8]
            final_list.append(flight)

        final_list.sort(key=lambda x: x["price"])

        return {
            "count": len(final_list),
            "total_records": len(all_prices),
            "min_price": min_overall_price if min_overall_price != float('inf') else 0,
            "platforms": list(all_platforms),
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
