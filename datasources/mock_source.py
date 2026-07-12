"""
Flight Monitor - Mock Data Source (Multi-Platform, Domestic + International)
Generates realistic flight price data from multiple booking platforms.
- Domestic routes: Ctrip, Qunar, Fliggy, Tongcheng + Chinese airline official sites
- International routes: Trip.com, Skyscanner, Google Flights, Kayak, Expedia + international airline official sites
Each platform has slightly different prices, simulating real-world comparison.
Prices fluctuate over time to simulate real market behavior.
"""
import random
import hashlib
from datetime import datetime, timedelta
from typing import List
from .base import BaseDataSource
from core.models import FlightPrice, SearchQuery
from config import (
    AIRLINES, AIRCRAFT_TYPES, CITY_CODES,
    PURCHASE_PLATFORMS, AIRLINE_OFFICIAL_SITES,
    LONG_HAUL_AIRCRAFT, SHORT_HAUL_AIRCRAFT,
    AIRLINE_CODES_EXTRA, CITY_GROUPS,
    DOMESTIC_AIRLINES, INTERNATIONAL_AIRLINES,
    ROUTE_AIRLINES, CITY_TO_REGION,
)

# ── Domestic OTA platforms ────────────────────────────────────
DOMESTIC_PLATFORMS = ["ctrip", "qunar", "fliggy", "tongcheng"]

# ── International OTA platforms ───────────────────────────────
INTERNATIONAL_PLATFORMS = ["tripcom", "skyscanner", "googleflights", "kayak", "expedia"]

# ── Airline code mapping for flight number generation ─────────
AIRLINE_CODES = {
    "中国国航": "CA", "南方航空": "CZ", "东方航空": "MU",
    "海南航空": "HU", "深圳航空": "ZH", "厦门航空": "MF",
    "四川航空": "3U", "山东航空": "SC", "春秋航空": "9C",
    "吉祥航空": "HO", "华夏航空": "G5", "长龙航空": "GJ",
    "成都航空": "EU", "首都航空": "JD", "天津航空": "GS",
}
AIRLINE_CODES.update(AIRLINE_CODES_EXTRA)

# ── Budget airlines (typically cheaper) ───────────────────────
BUDGET_AIRLINES = {"春秋航空", "吉祥航空", "华夏航空", "长龙航空"}

# ── Domestic route base prices (CNY, economy one-way off-peak) ─
# Calibrated to approximate real market prices on Ctrip
DOMESTIC_ROUTE_PRICES = {
    # 热门干线
    ("北京", "上海"): 780, ("上海", "北京"): 780,
    ("北京", "广州"): 950, ("广州", "北京"): 950,
    ("北京", "深圳"): 1050, ("深圳", "北京"): 1050,
    ("北京", "成都"): 850, ("成都", "北京"): 850,
    ("上海", "广州"): 680, ("广州", "上海"): 680,
    ("北京", "三亚"): 1300, ("三亚", "北京"): 1300,
    ("广州", "成都"): 580, ("成都", "广州"): 580,
    ("上海", "成都"): 850, ("成都", "上海"): 850,
    ("北京", "西安"): 580, ("西安", "北京"): 580,
    ("上海", "厦门"): 680, ("厦门", "上海"): 680,
    ("广州", "海口"): 480, ("海口", "广州"): 480,
    ("北京", "哈尔滨"): 580, ("哈尔滨", "北京"): 580,
    ("深圳", "成都"): 680, ("成都", "深圳"): 680,
    ("北京", "昆明"): 1100, ("昆明", "北京"): 1100,
    ("上海", "三亚"): 1300, ("三亚", "上海"): 1300,
    ("北京", "杭州"): 580, ("杭州", "北京"): 580,
    ("北京", "武汉"): 680, ("武汉", "北京"): 680,
    ("深圳", "上海"): 850, ("上海", "深圳"): 850,
    ("广州", "深圳"): 280, ("深圳", "广州"): 280,
    ("成都", "拉萨"): 1100, ("拉萨", "成都"): 1100,
    ("上海", "青岛"): 620, ("青岛", "上海"): 620,
    ("广州", "厦门"): 520, ("厦门", "广州"): 520,
    ("北京", "大连"): 520, ("大连", "北京"): 520,
    ("上海", "大连"): 720, ("大连", "上海"): 720,
    ("广州", "三亚"): 420, ("三亚", "广州"): 420,
    # 更多国内航线
    ("北京", "重庆"): 850, ("重庆", "北京"): 850,
    ("上海", "重庆"): 750, ("重庆", "上海"): 750,
    ("广州", "重庆"): 580, ("重庆", "广州"): 580,
    ("深圳", "重庆"): 620, ("重庆", "深圳"): 620,
    ("北京", "长沙"): 720, ("长沙", "北京"): 720,
    ("上海", "长沙"): 620, ("长沙", "上海"): 620,
    ("广州", "长沙"): 420, ("长沙", "广州"): 420,
    ("北京", "青岛"): 520, ("青岛", "北京"): 520,
    ("上海", "武汉"): 580, ("武汉", "上海"): 580,
    ("广州", "武汉"): 480, ("武汉", "广州"): 480,
    ("成都", "昆明"): 480, ("昆明", "成都"): 480,
    ("北京", "乌鲁木齐"): 1500, ("乌鲁木齐", "北京"): 1500,
    ("上海", "乌鲁木齐"): 1800, ("乌鲁木齐", "上海"): 1800,
    ("成都", "三亚"): 850, ("三亚", "成都"): 850,
    ("杭州", "广州"): 620, ("广州", "杭州"): 620,
    ("杭州", "成都"): 750, ("成都", "杭州"): 750,
    ("西安", "上海"): 720, ("上海", "西安"): 720,
    ("西安", "广州"): 680, ("广州", "西安"): 680,
    ("北京", "南京"): 580, ("南京", "北京"): 580,
    ("北京", "郑州"): 480, ("郑州", "北京"): 480,
    ("北京", "太原"): 420, ("太原", "北京"): 420,
    ("北京", "天津"): 280, ("天津", "北京"): 280,
}

# ── International route base prices (CNY, economy one-way off-peak) ────
INTL_ROUTE_PRICES = {
    # ── 港澳台 ──
    ("北京", "香港"): 1500, ("香港", "北京"): 1500,
    ("上海", "香港"): 1200, ("香港", "上海"): 1200,
    ("深圳", "香港"): 600,  ("香港", "深圳"): 600,
    ("广州", "香港"): 600,  ("香港", "广州"): 600,
    ("厦门", "台北"): 1200, ("台北", "厦门"): 1200,
    ("上海", "台北"): 1800, ("台北", "上海"): 1800,
    ("北京", "澳门"): 1800, ("澳门", "北京"): 1800,

    # ── 中日 ──
    ("北京", "东京"): 2800, ("东京", "北京"): 2800,
    ("上海", "东京"): 2000, ("东京", "上海"): 2000,
    ("北京", "大阪"): 2800, ("大阪", "北京"): 2800,
    ("上海", "大阪"): 2000, ("大阪", "上海"): 2000,
    ("上海", "名古屋"): 2000, ("名古屋", "上海"): 2000,
    ("北京", "福冈"): 2500, ("福冈", "北京"): 2500,
    ("上海", "福冈"): 1600, ("福冈", "上海"): 1600,
    ("北京", "札幌"): 3200, ("札幌", "北京"): 3200,
    ("上海", "冲绳"): 2000, ("冲绳", "上海"): 2000,
    ("广州", "东京"): 2800, ("东京", "广州"): 2800,
    ("大连", "东京"): 2000, ("东京", "大连"): 2000,

    # ── 中韩 ──
    ("北京", "首尔"): 2000, ("首尔", "北京"): 2000,
    ("上海", "首尔"): 1600, ("首尔", "上海"): 1600,
    ("青岛", "首尔"): 1200, ("首尔", "青岛"): 1200,
    ("广州", "首尔"): 2400, ("首尔", "广州"): 2400,
    ("上海", "釜山"): 1800, ("釜山", "上海"): 1800,
    ("上海", "济州岛"): 1500, ("济州岛", "上海"): 1500,

    # ── 东南亚 ──
    ("北京", "曼谷"): 2800, ("曼谷", "北京"): 2800,
    ("上海", "曼谷"): 2400, ("曼谷", "上海"): 2400,
    ("广州", "曼谷"): 1600, ("曼谷", "广州"): 1600,
    ("昆明", "曼谷"): 1200, ("曼谷", "昆明"): 1200,
    ("成都", "曼谷"): 1800, ("曼谷", "成都"): 1800,
    ("广州", "新加坡"): 1600, ("新加坡", "广州"): 1600,
    ("成都", "新加坡"): 2000, ("新加坡", "成都"): 2000,
    ("上海", "新加坡"): 2200, ("新加坡", "上海"): 2200,
    ("北京", "新加坡"): 2800, ("新加坡", "北京"): 2800,
    ("上海", "巴厘岛"): 2800, ("巴厘岛", "上海"): 2800,
    ("广州", "胡志明市"): 1600, ("胡志明市", "广州"): 1600,
    ("昆明", "清迈"): 1200, ("清迈", "昆明"): 1200,
    ("广州", "吉隆坡"): 1800, ("吉隆坡", "广州"): 1800,
    ("广州", "马尼拉"): 1600, ("马尼拉", "广州"): 1600,
    ("上海", "普吉岛"): 2800, ("普吉岛", "上海"): 2800,

    # ── 中东 ──
    ("北京", "迪拜"): 4500, ("迪拜", "北京"): 4500,
    ("上海", "迪拜"): 4000, ("迪拜", "上海"): 4000,
    ("广州", "迪拜"): 3800, ("迪拜", "广州"): 3800,
    ("北京", "多哈"): 5000, ("多哈", "北京"): 5000,
    ("广州", "多哈"): 4200, ("多哈", "广州"): 4200,
    ("上海", "多哈"): 4500, ("多哈", "上海"): 4500,

    # ── 欧洲 ──
    ("北京", "伦敦"): 5500, ("伦敦", "北京"): 5500,
    ("上海", "伦敦"): 5000, ("伦敦", "上海"): 5000,
    ("北京", "巴黎"): 5500, ("巴黎", "北京"): 5500,
    ("上海", "巴黎"): 5000, ("巴黎", "上海"): 5000,
    ("北京", "法兰克福"): 5000, ("法兰克福", "北京"): 5000,
    ("上海", "法兰克福"): 4500, ("法兰克福", "上海"): 4500,
    ("北京", "莫斯科"): 3800, ("莫斯科", "北京"): 3800,
    ("上海", "阿姆斯特丹"): 4800, ("阿姆斯特丹", "上海"): 4800,
    ("广州", "伊斯坦布尔"): 4500, ("伊斯坦布尔", "广州"): 4500,
    ("北京", "罗马"): 5000, ("罗马", "北京"): 5000,
    ("上海", "马德里"): 5000, ("马德里", "上海"): 5000,

    # ── 北美 ──
    ("北京", "纽约"): 6500, ("纽约", "北京"): 6500,
    ("上海", "纽约"): 6000, ("纽约", "上海"): 6000,
    ("北京", "洛杉矶"): 5500, ("洛杉矶", "北京"): 5500,
    ("上海", "洛杉矶"): 5000, ("洛杉矶", "上海"): 5000,
    ("北京", "旧金山"): 5500, ("旧金山", "北京"): 5500,
    ("上海", "旧金山"): 5000, ("旧金山", "上海"): 5000,
    ("香港", "旧金山"): 4800, ("旧金山", "香港"): 4800,
    ("北京", "西雅图"): 5200, ("西雅图", "北京"): 5200,
    ("上海", "多伦多"): 5500, ("多伦多", "上海"): 5500,
    ("广州", "洛杉矶"): 5000, ("洛杉矶", "广州"): 5000,

    # ── 大洋洲 ──
    ("北京", "悉尼"): 5500, ("悉尼", "北京"): 5500,
    ("上海", "悉尼"): 5000, ("悉尼", "上海"): 5000,
    ("广州", "悉尼"): 4200, ("悉尼", "广州"): 4200,
    ("广州", "墨尔本"): 4200, ("墨尔本", "广州"): 4200,
    ("上海", "墨尔本"): 4800, ("墨尔本", "上海"): 4800,
    ("上海", "奥克兰"): 5200, ("奥克兰", "上海"): 5200,

    # ── 区域内国际 ──
    ("东京", "首尔"): 1800, ("首尔", "东京"): 1800,
    ("东京", "曼谷"): 2800, ("曼谷", "东京"): 2800,
    ("首尔", "曼谷"): 2400, ("曼谷", "首尔"): 2400,
    ("新加坡", "巴厘岛"): 1200, ("巴厘岛", "新加坡"): 1200,
    ("伦敦", "巴黎"): 1000, ("巴黎", "伦敦"): 1000,
    ("纽约", "洛杉矶"): 2000, ("洛杉矶", "纽约"): 2000,
    ("纽约", "伦敦"): 3500, ("伦敦", "纽约"): 3500,
    ("伦敦", "迪拜"): 2800, ("迪拜", "伦敦"): 2800,
    ("东京", "新加坡"): 3200, ("新加坡", "东京"): 3200,
}

# ── Region classification for route type detection ────────────
DOMESTIC_CITIES = set(CITY_GROUPS.get("中国大陆", []))

# ── Airport name mapping ──────────────────────────────────────
AIRPORTS = {
    # 国内
    "北京": [("北京首都", "PEK"), ("北京大兴", "PKX")],
    "上海": [("上海虹桥", "SHA"), ("上海浦东", "PVG")],
    "广州": [("广州白云", "CAN")],
    "深圳": [("深圳宝安", "SZX")],
    "成都": [("成都双流", "CTU"), ("成都天府", "TFU")],
    "杭州": [("杭州萧山", "HGH")],
    "西安": [("西安咸阳", "XIY")],
    "三亚": [("三亚凤凰", "SYX")],
    "海口": [("海口美兰", "HAK")],
    "厦门": [("厦门高崎", "XMN")],
    "昆明": [("昆明长水", "KMG")],
    "哈尔滨": [("哈尔滨太平", "HRB")],
    "青岛": [("青岛胶东", "TAO")],
    "大连": [("大连周水子", "DLC")],
    "拉萨": [("拉萨贡嘎", "LXA")],
    "武汉": [("武汉天河", "WUH")],
    "重庆": [("重庆江北", "CKG")],
    "南京": [("南京禄口", "NKG")],
    "长沙": [("长沙黄花", "CSX")],
    "郑州": [("郑州新郑", "CGO")],
    "天津": [("天津滨海", "TSN")],
    # 港澳台
    "香港": [("香港国际机场", "HKG")],
    "澳门": [("澳门国际机场", "MFM")],
    "台北": [("桃园国际机场", "TPE")],
    "高雄": [("高雄国际机场", "KHH")],
    # 日本
    "东京": [("羽田机场", "HND"), ("成田机场", "NRT")],
    "大阪": [("关西国际机场", "KIX"), ("大阪伊丹", "ITM")],
    "名古屋": [("中部国际机场", "NGO")],
    "福冈": [("福冈机场", "FUK")],
    "札幌": [("新千岁机场", "CTS")],
    "冲绳": [("那霸机场", "OKA")],
    # 韩国
    "首尔": [("仁川国际机场", "ICN"), ("金浦机场", "GMP")],
    "釜山": [("金海国际机场", "PUS")],
    "济州岛": [("济州国际机场", "CJU")],
    # 东南亚
    "新加坡": [("樟宜机场", "SIN")],
    "曼谷": [("素万那普机场", "BKK"), ("廊曼机场", "DMK")],
    "吉隆坡": [("吉隆坡国际机场", "KUL")],
    "河内": [("内排国际机场", "HAN")],
    "胡志明市": [("新山一机场", "SGN")],
    "巴厘岛": [("伍拉莱机场", "DPS")],
    "普吉岛": [("普吉国际机场", "HKT")],
    "清迈": [("清迈国际机场", "CNX")],
    "马尼拉": [("尼诺伊·阿基诺", "MNL")],
    "雅加达": [("苏加诺-哈达", "CGK")],
    # 中东
    "迪拜": [("迪拜国际机场", "DXB")],
    "多哈": [("哈马德国际机场", "DOH")],
    "德里": [("英迪拉·甘地", "DEL")],
    "孟买": [("贾特拉帕蒂·希瓦吉", "BOM")],
    # 欧洲
    "伦敦": [("希思罗机场", "LHR"), ("盖特威克", "LGW")],
    "巴黎": [("戴高乐机场", "CDG"), ("奥利机场", "ORY")],
    "法兰克福": [("法兰克福机场", "FRA")],
    "阿姆斯特丹": [("史基浦机场", "AMS")],
    "罗马": [("菲乌米奇诺", "FCO")],
    "米兰": [("马尔彭萨", "MXP")],
    "马德里": [("巴拉哈斯", "MAD")],
    "慕尼黑": [("慕尼黑机场", "MUC")],
    "莫斯科": [("谢列梅捷沃", "SVO")],
    "伊斯坦布尔": [("新伊斯坦布尔机场", "IST")],
    "苏黎世": [("苏黎世机场", "ZRH")],
    "维也纳": [("维也纳机场", "VIE")],
    # 北美
    "纽约": [("JFK", "JFK"), ("纽瓦克", "EWR"), ("拉瓜迪亚", "LGA")],
    "洛杉矶": [("LAX", "LAX")],
    "旧金山": [("SFO", "SFO")],
    "芝加哥": [("奥黑尔", "ORD")],
    "波士顿": [("洛根", "BOS")],
    "西雅图": [("西雅图-塔科马", "SEA")],
    "多伦多": [("皮尔逊", "YYZ")],
    "温哥华": [("温哥华机场", "YVR")],
    "华盛顿": [("杜勒斯", "IAD")],
    "迈阿密": [("迈阿密国际", "MIA")],
    # 大洋洲
    "悉尼": [("悉尼金斯福德", "SYD")],
    "墨尔本": [("墨尔本机场", "MEL")],
    "奥克兰": [("奥克兰机场", "AKL")],
    "布里斯班": [("布里斯班机场", "BNE")],
}


def is_international_route(departure: str, destination: str) -> bool:
    """Check if a route is international (both not domestic mainland)."""
    dep_domestic = departure in DOMESTIC_CITIES
    arr_domestic = destination in DOMESTIC_CITIES
    return not (dep_domestic and arr_domestic)


def get_route_base_price(departure: str, destination: str) -> int:
    """Get base price for a route, with fallback estimation."""
    # Check domestic prices
    price = DOMESTIC_ROUTE_PRICES.get((departure, destination))
    if price:
        return price

    # Check international prices
    price = INTL_ROUTE_PRICES.get((departure, destination))
    if price:
        return price

    # Fallback: estimate based on whether international
    if is_international_route(departure, destination):
        dep_code = CITY_CODES.get(departure, "")
        arr_code = CITY_CODES.get(destination, "")
        # If both sides have known codes, estimate higher
        if dep_code and arr_code:
            return random.randint(2500, 5000)
        return 3500
    else:
        return random.randint(500, 1200)


def build_purchase_url(platform_key: str, departure: str, destination: str,
                       date: str, airline: str = "") -> str:
    """Build a purchase URL for a given platform and route."""
    plat = PURCHASE_PLATFORMS.get(platform_key)
    if not plat:
        return ""
    dep_code = CITY_CODES.get(departure, "")
    arr_code = CITY_CODES.get(destination, "")
    try:
        return plat["url"].format(
            dep=departure, arr=destination, date=date,
            dep_code=dep_code, arr_code=arr_code,
        )
    except (KeyError, IndexError):
        return plat["url"]


class MockDataSource(BaseDataSource):
    """Simulated multi-platform flight data source with realistic price behavior.
    Supports both domestic (China) and international routes."""

    name = "mock"

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Generate realistic flight results from multiple platforms."""
        intl = is_international_route(query.departure, query.destination)
        base_price = get_route_base_price(query.departure, query.destination)

        # Deterministic seed based on route+date
        seed_str = f"{query.departure}{query.destination}{query.departure_date}"
        seed_base = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)

        # Time-based fluctuation
        now = datetime.now()
        time_factor = (now.hour * 60 + now.minute) / 1440.0

        # Days until departure affects price
        try:
            dep_date = datetime.strptime(query.departure_date, "%Y-%m-%d")
            days_until = max(0, (dep_date - now).days)
        except ValueError:
            days_until = 30

        if days_until > 60:
            day_factor = 0.85
        elif days_until > 30:
            day_factor = 0.90
        elif days_until > 14:
            day_factor = 0.95
        elif days_until > 7:
            day_factor = 1.05
        elif days_until > 3:
            day_factor = 1.15
        elif days_until > 1:
            day_factor = 1.25
        else:
            day_factor = 1.40

        # Cabin class multiplier
        cabin_mult = {"economy": 1.0, "business": 2.8, "first": 4.5}.get(
            query.cabin_class, 1.0
        )

        # Select airlines: domestic routes use only domestic airlines;
        # international routes use route-specific airline selection
        if intl:
            # Look up route-specific airlines based on regions
            dep_region = CITY_TO_REGION.get(query.departure, "")
            arr_region = CITY_TO_REGION.get(query.destination, "")
            route_airlines = ROUTE_AIRLINES.get((dep_region, arr_region))

            if route_airlines:
                # Use route-specific airline list
                num_flights = min(random.randint(5, 8), len(route_airlines))
                used_airlines = random.sample(route_airlines, num_flights)
            else:
                # Fallback: mix of Chinese majors + relevant international airlines
                chinese_majors = ["中国国航", "南方航空", "东方航空", "海南航空"]
                fallback_pool = chinese_majors + [
                    a for a in INTERNATIONAL_AIRLINES
                    if a not in chinese_majors
                ][:8]
                num_flights = random.randint(5, 8)
                used_airlines = random.sample(
                    fallback_pool, min(num_flights, len(fallback_pool))
                )
            aircraft_pool = LONG_HAUL_AIRCRAFT
        else:
            # Domestic routes: only use Chinese domestic airlines
            num_flights = random.randint(8, 12)
            used_airlines = random.sample(
                DOMESTIC_AIRLINES, min(num_flights, len(DOMESTIC_AIRLINES))
            )
            aircraft_pool = SHORT_HAUL_AIRCRAFT

        # Select platforms based on route type
        if intl:
            ota_platforms = INTERNATIONAL_PLATFORMS
        else:
            ota_platforms = DOMESTIC_PLATFORMS

        dep_airports = AIRPORTS.get(
            query.departure, [(f"{query.departure}机场", "XXX")]
        )
        arr_airports = AIRPORTS.get(
            query.destination, [(f"{query.destination}机场", "XXX")]
        )

        all_flights: List[FlightPrice] = []

        for i in range(num_flights):
            flight_seed = seed_base + i * 7919 + int(time_factor * 100000)
            rng = random.Random(flight_seed)

            airline = used_airlines[i % len(used_airlines)]

            # Generate departure time first (needed for peak-hour pricing)
            dep_hour = rng.randint(6, 22)
            dep_minute = rng.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
            dep_time = f"{dep_hour:02d}:{dep_minute:02d}"

            # Price variation: wider range for realistic spread
            # Budget airlines are 20-40% cheaper; peak hours cost more
            price_variation = rng.uniform(0.70, 1.30)
            if airline in BUDGET_AIRLINES:
                price_variation *= rng.uniform(0.65, 0.80)
            # Peak hours (morning 7-9, evening 17-20) cost more
            if 7 <= dep_hour <= 9 or 17 <= dep_hour <= 20:
                price_variation *= rng.uniform(1.05, 1.20)
            # Early morning / late night cheaper
            if dep_hour < 7:
                price_variation *= rng.uniform(0.80, 0.90)

            base_flight_price = base_price * day_factor * price_variation * cabin_mult
            base_flight_price = round(base_flight_price / 10) * 10
            base_flight_price = max(120 if not intl else 300, base_flight_price)

            # Duration: international routes are much longer
            if intl:
                # Estimate flight duration from base price (proxy for distance)
                duration_hours = max(2, int(base_price / 800))
                duration_minutes = rng.randint(20, 55)
                # Some long-haul routes can be 12+ hours
                if base_price > 6000:
                    duration_hours = max(duration_hours, rng.randint(10, 15))
                elif base_price > 4000:
                    duration_hours = max(duration_hours, rng.randint(7, 12))
                elif base_price > 2500:
                    duration_hours = max(duration_hours, rng.randint(4, 8))
            else:
                duration_hours = max(1, int(base_price / 600))
                duration_minutes = rng.randint(10, 55)

            total_dep_minutes = dep_hour * 60 + dep_minute
            total_arr_minutes = total_dep_minutes + duration_hours * 60 + duration_minutes
            # Handle next-day arrival
            day_offset = total_arr_minutes // (24 * 60)
            arr_hour = (total_arr_minutes // 60) % 24
            arr_minute = total_arr_minutes % 60
            arr_time = f"{arr_hour:02d}:{arr_minute:02d}"
            if day_offset > 0:
                arr_time += f" +{day_offset}d"
            duration_str = f"{duration_hours}h{duration_minutes}m"

            # Stops: international more likely to have 1 stop
            if intl:
                stops = 0 if rng.random() > 0.45 else (1 if rng.random() > 0.15 else 2)
            else:
                stops = 0 if rng.random() > 0.2 else 1

            dep_ap = rng.choice(dep_airports)
            arr_ap = rng.choice(arr_airports)
            code = AIRLINE_CODES.get(airline, "XX")
            flight_no = f"{code}{rng.randint(100, 9999)}"
            aircraft = rng.choice(aircraft_pool)

            # ── Generate one price entry per OTA platform ──────
            for plat_key in ota_platforms:
                plat_seed_val = sum(ord(c) for c in plat_key) % 10000
                plat_rng = random.Random(flight_seed + plat_seed_val)
                # Platform price variation: -5% to +8%
                plat_factor = plat_rng.uniform(0.95, 1.08)
                # Some platforms have promotional discounts
                if plat_key == "qunar":
                    plat_factor *= plat_rng.uniform(0.95, 1.0)
                elif plat_key == "fliggy":
                    plat_factor *= plat_rng.uniform(0.96, 1.02)
                elif plat_key == "skyscanner":
                    plat_factor *= plat_rng.uniform(0.97, 1.03)
                elif plat_key == "kayak":
                    plat_factor *= plat_rng.uniform(0.96, 1.02)
                elif plat_key == "googleflights":
                    plat_factor *= plat_rng.uniform(0.98, 1.04)

                plat_price = round(base_flight_price * plat_factor / 10) * 10
                plat_price = max(120 if not intl else 300, plat_price)

                all_flights.append(FlightPrice(
                    query_id=query.id or 0,
                    airline=airline,
                    flight_no=flight_no,
                    aircraft=aircraft,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    departure_airport=dep_ap[0],
                    arrival_airport=arr_ap[0],
                    duration=duration_str,
                    stops=stops,
                    price=plat_price,
                    cabin_class=query.cabin_class,
                    source=plat_key,
                    recorded_at=now.isoformat(),
                    purchase_url=build_purchase_url(
                        plat_key, query.departure, query.destination,
                        query.departure_date, airline
                    ),
                ))

            # ── Also add airline official website price ──────
            official_key = AIRLINE_OFFICIAL_SITES.get(airline)
            if official_key and official_key in PURCHASE_PLATFORMS:
                official_seed_val = sum(ord(c) for c in official_key) % 10000
                official_rng = random.Random(
                    flight_seed + official_seed_val
                )
                # Official sites sometimes match or slightly undercut OTA prices
                official_factor = official_rng.uniform(0.97, 1.05)
                official_price = round(base_flight_price * official_factor / 10) * 10
                official_price = max(120 if not intl else 300, official_price)

                all_flights.append(FlightPrice(
                    query_id=query.id or 0,
                    airline=airline,
                    flight_no=flight_no,
                    aircraft=aircraft,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    departure_airport=dep_ap[0],
                    arrival_airport=arr_ap[0],
                    duration=duration_str,
                    stops=stops,
                    price=official_price,
                    cabin_class=query.cabin_class,
                    source=official_key,
                    recorded_at=now.isoformat(),
                    purchase_url=build_purchase_url(
                        official_key, query.departure, query.destination,
                        query.departure_date, airline
                    ),
                ))

        # Sort by price
        all_flights.sort(key=lambda f: f.price)
        return all_flights
