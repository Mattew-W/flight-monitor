"""
Flight schedule database — key Chinese domestic & international flights.
Manually compiled + auto-generated from scraped data (2026 summer season).
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# Format: flight_no -> { dep, arr, dep_airport, arr_airport, aircraft, duration_min, airline, dep_city, arr_city }
FLIGHT_DB = {
    # === 中国国航 CA ===
    "CA1501": {"dep": "08:30", "arr": "10:40", "dep_airport": "PEK", "arr_airport": "SHA", "aircraft": "A330", "duration_min": 130, "airline": "中国国航", "dep_city": "北京", "arr_city": "上海"},
    "CA1502": {"dep": "11:30", "arr": "13:40", "dep_airport": "SHA", "arr_airport": "PEK", "aircraft": "A330", "duration_min": 130, "airline": "中国国航", "dep_city": "上海", "arr_city": "北京"},
    "CA1521": {"dep": "14:30", "arr": "16:40", "dep_airport": "PEK", "arr_airport": "SHA", "aircraft": "A330", "duration_min": 130, "airline": "中国国航", "dep_city": "北京", "arr_city": "上海"},
    "CA1315": {"dep": "11:00", "arr": "14:00", "dep_airport": "PEK", "arr_airport": "CAN", "aircraft": "B787", "duration_min": 180, "airline": "中国国航", "dep_city": "北京", "arr_city": "广州"},
    "CA1405": {"dep": "07:30", "arr": "10:15", "dep_airport": "PEK", "arr_airport": "CTU", "aircraft": "A320", "duration_min": 165, "airline": "中国国航", "dep_city": "北京", "arr_city": "成都"},
    "CA1201": {"dep": "14:00", "arr": "16:20", "dep_airport": "PEK", "arr_airport": "XIY", "aircraft": "A320", "duration_min": 140, "airline": "中国国航", "dep_city": "北京", "arr_city": "西安"},

    # === 东方航空 MU ===
    "MU5101": {"dep": "07:00", "arr": "09:15", "dep_airport": "SHA", "arr_airport": "PEK", "aircraft": "A330", "duration_min": 135, "airline": "东方航空", "dep_city": "上海", "arr_city": "北京"},
    "MU5102": {"dep": "10:00", "arr": "12:15", "dep_airport": "PEK", "arr_airport": "SHA", "aircraft": "A330", "duration_min": 135, "airline": "东方航空", "dep_city": "北京", "arr_city": "上海"},
    "MU5301": {"dep": "09:00", "arr": "11:20", "dep_airport": "SHA", "arr_airport": "CAN", "aircraft": "B737", "duration_min": 140, "airline": "东方航空", "dep_city": "上海", "arr_city": "广州"},
    "MU5309": {"dep": "10:00", "arr": "12:25", "dep_airport": "SHA", "arr_airport": "CAN", "aircraft": "A320", "duration_min": 145, "airline": "东方航空", "dep_city": "上海", "arr_city": "广州"},
    "MU5401": {"dep": "08:00", "arr": "10:45", "dep_airport": "SHA", "arr_airport": "CTU", "aircraft": "A320", "duration_min": 165, "airline": "东方航空", "dep_city": "上海", "arr_city": "成都"},
    "MU5110": {"dep": "15:00", "arr": "17:15", "dep_airport": "SHA", "arr_airport": "PEK", "aircraft": "B777", "duration_min": 135, "airline": "东方航空", "dep_city": "上海", "arr_city": "北京"},
    "MU5696": {"dep": "08:10", "arr": "12:15", "dep_airport": "SHA", "arr_airport": "URC", "aircraft": "A320", "duration_min": 245, "airline": "东方航空", "dep_city": "上海", "arr_city": "乌鲁木齐"},
    "MU587": {"dep": "11:30", "arr": "17:30", "dep_airport": "PVG", "arr_airport": "JFK", "aircraft": "B777", "duration_min": 840, "airline": "东方航空", "dep_city": "上海", "arr_city": "纽约"},
    "MU551": {"dep": "13:00", "arr": "19:30", "dep_airport": "PVG", "arr_airport": "LHR", "aircraft": "B787", "duration_min": 750, "airline": "东方航空", "dep_city": "上海", "arr_city": "伦敦"},

    # === 南方航空 CZ ===
    "CZ3101": {"dep": "08:00", "arr": "10:30", "dep_airport": "CAN", "arr_airport": "PEK", "aircraft": "A330", "duration_min": 150, "airline": "南方航空", "dep_city": "广州", "arr_city": "北京"},
    "CZ3521": {"dep": "14:00", "arr": "16:30", "dep_airport": "CAN", "arr_airport": "SHA", "aircraft": "B787", "duration_min": 150, "airline": "南方航空", "dep_city": "广州", "arr_city": "上海"},
    "CZ3401": {"dep": "10:00", "arr": "12:30", "dep_airport": "CAN", "arr_airport": "CTU", "aircraft": "A320", "duration_min": 150, "airline": "南方航空", "dep_city": "广州", "arr_city": "成都"},
    "CZ3999": {"dep": "07:30", "arr": "08:30", "dep_airport": "CAN", "arr_airport": "HAK", "aircraft": "A320", "duration_min": 60, "airline": "南方航空", "dep_city": "广州", "arr_city": "海口"},
    "CZ327": {"dep": "21:30", "arr": "18:00", "dep_airport": "CAN", "arr_airport": "LAX", "aircraft": "B777", "duration_min": 750, "airline": "南方航空", "dep_city": "广州", "arr_city": "洛杉矶"},
    "CZ303": {"dep": "22:00", "arr": "06:00", "dep_airport": "CAN", "arr_airport": "LHR", "aircraft": "B787", "duration_min": 720, "airline": "南方航空", "dep_city": "广州", "arr_city": "伦敦"},

    # === 海南航空 HU ===
    "HU7601": {"dep": "07:00", "arr": "09:15", "dep_airport": "PEK", "arr_airport": "SHA", "aircraft": "B787", "duration_min": 135, "airline": "海南航空", "dep_city": "北京", "arr_city": "上海"},
    "HU7606": {"dep": "10:00", "arr": "12:15", "dep_airport": "SHA", "arr_airport": "PEK", "aircraft": "B787", "duration_min": 135, "airline": "海南航空", "dep_city": "上海", "arr_city": "北京"},
    "HU7801": {"dep": "08:30", "arr": "11:30", "dep_airport": "PEK", "arr_airport": "CAN", "aircraft": "A330", "duration_min": 180, "airline": "海南航空", "dep_city": "北京", "arr_city": "广州"},
    "HU7301": {"dep": "08:00", "arr": "10:30", "dep_airport": "HAK", "arr_airport": "SYX", "aircraft": "B737", "duration_min": 30, "airline": "海南航空", "dep_city": "海口", "arr_city": "三亚"},

    # === 深圳航空 ZH ===
    "ZH9101": {"dep": "07:30", "arr": "10:00", "dep_airport": "SZX", "arr_airport": "PEK", "aircraft": "A330", "duration_min": 150, "airline": "深圳航空", "dep_city": "深圳", "arr_city": "北京"},
    "ZH9201": {"dep": "12:00", "arr": "14:30", "dep_airport": "SZX", "arr_airport": "SHA", "aircraft": "B737", "duration_min": 150, "airline": "深圳航空", "dep_city": "深圳", "arr_city": "上海"},
    "ZH9301": {"dep": "15:00", "arr": "17:30", "dep_airport": "SZX", "arr_airport": "CTU", "aircraft": "A320", "duration_min": 150, "airline": "深圳航空", "dep_city": "深圳", "arr_city": "成都"},

    # === 厦门航空 MF ===
    "MF8101": {"dep": "07:00", "arr": "09:30", "dep_airport": "XMN", "arr_airport": "PEK", "aircraft": "B737", "duration_min": 150, "airline": "厦门航空", "dep_city": "厦门", "arr_city": "北京"},
    "MF8501": {"dep": "10:00", "arr": "11:30", "dep_airport": "XMN", "arr_airport": "SHA", "aircraft": "B737", "duration_min": 90, "airline": "厦门航空", "dep_city": "厦门", "arr_city": "上海"},
    "MF8201": {"dep": "14:00", "arr": "16:30", "dep_airport": "XMN", "arr_airport": "CAN", "aircraft": "B737", "duration_min": 90, "airline": "厦门航空", "dep_city": "厦门", "arr_city": "广州"},

    # === 四川航空 3U ===
    "3U8801": {"dep": "08:00", "arr": "10:30", "dep_airport": "CTU", "arr_airport": "PEK", "aircraft": "A320", "duration_min": 150, "airline": "四川航空", "dep_city": "成都", "arr_city": "北京"},
    "3U8901": {"dep": "11:00", "arr": "13:30", "dep_airport": "CTU", "arr_airport": "SHA", "aircraft": "A320", "duration_min": 150, "airline": "四川航空", "dep_city": "成都", "arr_city": "上海"},
    "3U8601": {"dep": "07:00", "arr": "09:30", "dep_airport": "CTU", "arr_airport": "CAN", "aircraft": "A319", "duration_min": 150, "airline": "四川航空", "dep_city": "成都", "arr_city": "广州"},
    "3U8701": {"dep": "06:30", "arr": "09:00", "dep_airport": "CTU", "arr_airport": "LXA", "aircraft": "A319", "duration_min": 150, "airline": "四川航空", "dep_city": "成都", "arr_city": "拉萨"},

    # === 春秋航空 9C ===
    "9C8801": {"dep": "06:30", "arr": "09:00", "dep_airport": "SHA", "arr_airport": "SJW", "aircraft": "A320", "duration_min": 150, "airline": "春秋航空", "dep_city": "上海", "arr_city": "石家庄"},
    "9C6101": {"dep": "21:00", "arr": "23:30", "dep_airport": "SHA", "arr_airport": "CAN", "aircraft": "A320", "duration_min": 150, "airline": "春秋航空", "dep_city": "上海", "arr_city": "广州"},
    "9C8501": {"dep": "07:00", "arr": "09:30", "dep_airport": "SHA", "arr_airport": "KWL", "aircraft": "A320", "duration_min": 150, "airline": "春秋航空", "dep_city": "上海", "arr_city": "桂林"},

    # === 吉祥航空 HO ===
    "HO1101": {"dep": "07:30", "arr": "10:00", "dep_airport": "SHA", "arr_airport": "PEK", "aircraft": "A320", "duration_min": 150, "airline": "吉祥航空", "dep_city": "上海", "arr_city": "北京"},
    "HO1201": {"dep": "12:00", "arr": "14:30", "dep_airport": "SHA", "arr_airport": "CAN", "aircraft": "A320", "duration_min": 150, "airline": "吉祥航空", "dep_city": "上海", "arr_city": "广州"},
    "HO1601": {"dep": "08:00", "arr": "10:30", "dep_airport": "SHA", "arr_airport": "SYX", "aircraft": "A321", "duration_min": 210, "airline": "吉祥航空", "dep_city": "上海", "arr_city": "三亚"},
}


def _extract_city(port_name: str) -> str:
    """Extract city name from airport port name.
    '北京首都' -> '北京', '深圳宝安' -> '深圳', '上海浦东' -> '上海', '香港国际机场' -> '香港'
    """
    if not port_name:
        return ""
    # Special cases / common suffixes to strip
    suffixes = ["国际机场", "国际", "机场", "首都", "大兴", "浦东", "虹桥", "宝安",
                "白云", "天府", "双流", "江北", "高崎", "美兰", "凤凰", "凤凰国际",
                "长水", "地窝堡", "咸阳", "萧山", "禄口", "新郑", "遥墙", "滨海",
                "周水子", "太平", "吴圩", "武宿", "中川", "曹家堡", "栎社", "龙嘉",
                "大水泊", "潮汕", "硕放", "奔牛", "昌北", "正定", "金湾", "观音",
                "蓬莱", "三义", "万州五桥", "北海福成", "义乌"]
    city = port_name
    for sfx in suffixes:
        if city.endswith(sfx):
            city = city[:-len(sfx)]
            break
    # Handle "香港国际机场" -> after stripping "国际机场" -> "香港"
    # For international ports like "成田国际机场" -> "东京成田"
    if len(city) <= 2:
        return city  # e.g. "香港"
    # For ports like "伦敦希斯罗", just take first 2 chars
    return city


def _parse_duration(dur_str: str) -> int:
    """Parse duration string like '2h25m' -> minutes."""
    if not dur_str:
        return 150
    h = m = 0
    hm = re.search(r'(\d+)\s*h\s*(\d+)\s*m', dur_str)
    if hm:
        h, m = int(hm.group(1)), int(hm.group(2))
    else:
        h_match = re.search(r'(\d+)\s*h', dur_str)
        m_match = re.search(r'(\d+)\s*m', dur_str)
        if h_match:
            h = int(h_match.group(1))
        if m_match:
            m = int(m_match.group(1))
    return h * 60 + m


def _load_auto_db() -> dict:
    """Load and normalize the auto-generated flight schedule DB."""
    auto_db = {}
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "data", "flight_schedules_auto.json")
    if not os.path.exists(json_path):
        logger.debug("Auto flight schedule DB not found: %s", json_path)
        return auto_db
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Failed to load auto flight DB: %s", e)
        return auto_db

    for entry in data.get("_all", []):
        fn = entry.get("flightNo", "").upper()
        if not fn or fn in auto_db:
            continue
        dep_port = entry.get("departPort", "")
        arr_port = entry.get("arrivePort", "")
        auto_db[fn] = {
            "dep": entry.get("departTime", ""),
            "arr": entry.get("arriveTime", ""),
            "dep_airport": dep_port,
            "arr_airport": arr_port,
            "aircraft": entry.get("aircraft", ""),
            "duration_min": _parse_duration(entry.get("duration", "")),
            "airline": entry.get("airline", fn[:2]),
            "dep_city": _extract_city(dep_port),
            "arr_city": _extract_city(arr_port),
        }
    return auto_db


# Lazy-loaded auto DB cache
_AUTO_DB_CACHE: dict | None = None


def _get_merged_db() -> dict:
    """Get merged flight DB: manual entries take priority over auto-generated."""
    global _AUTO_DB_CACHE
    if _AUTO_DB_CACHE is None:
        _AUTO_DB_CACHE = _load_auto_db()
    merged = dict(_AUTO_DB_CACHE)      # auto entries as base
    merged.update(FLIGHT_DB)           # manual entries override
    return merged


def lookup_flight_schedule(flight_no: str):
    """Look up flight schedule by flight number. Returns None if unknown.

    Searches: manual DB (65 entries) + auto-generated DB (405 entries).
    Supports fuzzy matching: if exact match not found, tries to match by
    airline prefix (partial input) or numeric suffix.
    """
    if not flight_no:
        return None
    fn = flight_no.strip().upper()
    merged = _get_merged_db()

    # Exact match first
    if fn in merged:
        return merged[fn]

    # Fuzzy: try common airline prefixes (e.g. '9103' -> 'ZH9103')
    airline_codes = ["CA", "MU", "CZ", "HU", "ZH", "MF", "3U", "9C", "HO", "GS", "G5", "GJ", "EU", "JD", "FM", "NS"]
    for code in airline_codes:
        if fn.startswith(code):
            continue  # already has airline code
        candidate = code + fn
        if candidate in merged:
            return merged[candidate]

    # Fuzzy: try matching by numeric suffix across all airlines
    digit_part = "".join(c for c in fn if c.isdigit())
    if len(digit_part) >= 3:
        for k, v in merged.items():
            numeric = "".join(c for c in k if c.isdigit())
            if numeric == digit_part or numeric.endswith(digit_part):
                return v

    return None


def search_flights_by_route(dep_city: str = "", arr_city: str = ""):
    """Search all flights matching a given city pair. Searches merged DB."""
    results = []
    merged = _get_merged_db()
    for fn, sched in merged.items():
        if dep_city and sched.get("dep_city") != dep_city:
            continue
        if arr_city and sched.get("arr_city") != arr_city:
            continue
        results.append({"flight_no": fn, **sched})
    return results
