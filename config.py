"""
Flight Monitor - Configuration
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Database
DB_PATH = os.path.join(BASE_DIR, "flight_monitor.db")

# Flask
HOST = "127.0.0.1"
PORT = 5566
DEBUG = False

# Monitor
MONITOR_INTERVAL_SECONDS = 300  # 5 minutes default polling interval

# Notification
# Email settings (leave empty to disable; prefer env vars: SMTP_HOST, SMTP_PASS, etc.)
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

# Server Chan (WeChat push) - https://sct.ftqq.com/
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")

# Feishu webhook
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")

# ==============================================================
# Data Sources
# ==============================================================

# Which data sources are enabled (mock simulates all platforms)
ENABLED_SOURCES = ["mock", "ctrip_browser"]

# ── Domestic Platform / Purchase Channel Definitions ───────────
# Each platform has: display name, color, icon, and a URL template
# URL templates use {dep}, {arr}, {date}, {dep_code}, {arr_code}
PURCHASE_PLATFORMS = {
    # ── OTA 平台（国内）──
    "ctrip": {
        "name": "携程旅行",
        "color": "#0086f6",
        "icon": "🛫",
        "url": "https://flights.ctrip.com/online/list/oneway-{dep_code}-{arr_code}?depdate={date}&cabin=y_s&adult=1&child=0&infant=0",
    },
    "qunar": {
        "name": "去哪儿",
        "color": "#3cae3e",
        "icon": "🐪",
        "url": "https://flight.qunar.com/site/oneway_list.htm?searchDepartureAirport={dep}&searchArrivalAirport={arr}&searchDepartureTime={date}&fromCode={dep_code}&toCode={arr_code}",
    },
    "fliggy": {
        "name": "飞猪旅行",
        "color": "#ff6a00",
        "icon": "🐷",
        "url": "https://s.fliggy.com/flight/search?from={dep}&to={arr}&date={date}&adult=1&child=0",
    },
    "tongcheng": {
        "name": "同程旅行",
        "color": "#2d8cf0",
        "icon": "🚂",
        "url": "https://www.ly.com/flights/itinerary/oneway/{dep}-{arr}?date={date}",
    },
    # ── 国内航司官网 ──
    "airchina": {
        "name": "国航官网",
        "color": "#e8211a",
        "icon": "✈️",
        "url": "https://www.airchina.com.cn/swp/index/flightSearch?tripType=0&depCity={dep}&arrCity={arr}&depDate={date}&cabin=y_s",
    },
    "csair": {
        "name": "南航官网",
        "color": "#005bac",
        "icon": "✈️",
        "url": "https://www.csair.com/zh-CN/touch/shopping/domestic/domestic-ticket-search?dep={dep}&arr={arr}&depDate={date}",
    },
    "ceair": {
        "name": "东航官网",
        "color": "#1a2a6c",
        "icon": "✈️",
        "url": "https://www.ceair.com/booking/{dep_code}-{arr_code}-{date}?cabinType=economy",
    },
    "hainan": {
        "name": "海航官网",
        "color": "#c7000b",
        "icon": "✈️",
        "url": "https://www.hnair.com/?dep={dep}&arr={arr}&date={date}",
    },
    "spring": {
        "name": "春秋航空",
        "color": "#51c7d0",
        "icon": "🍃",
        "url": "https://www.ch.com/flight?dep={dep}&arr={arr}&depDate={date}",
    },
    "juneyao": {
        "name": "吉祥航空",
        "color": "#7c3aed",
        "icon": "🍀",
        "url": "https://www.juneyaoair.com/?dep={dep}&arr={arr}&date={date}",
    },
    # ── 国际 OTA 平台 ──
    "tripcom": {
        "name": "Trip.com",
        "color": "#0086f6",
        "icon": "🌍",
        "url": "https://www.trip.com/flights/showfare?depCityCode={dep_code}&arrCityCode={arr_code}&depDate={date}&cabinType=economy",
    },
    "skyscanner": {
        "name": "Skyscanner",
        "color": "#0770e3",
        "icon": "🔍",
        "url": "https://www.skyscanner.com/transport/flights/{dep_code}/{arr_code}/{date}/?adultsv2=1&cabinclass=economy",
    },
    "googleflights": {
        "name": "Google Flights",
        "color": "#4285f4",
        "icon": "🔎",
        "url": "https://www.google.com/travel/flights?q=Flights+from+{dep_code}+to+{arr_code}+on+{date}&curr=CNY",
    },
    "kayak": {
        "name": "Kayak",
        "color": "#ff690f",
        "icon": "🛬",
        "url": "https://www.kayak.com/flights/{dep_code}-{arr_code}/{date}?adults=1&eco=1",
    },
    "expedia": {
        "name": "Expedia",
        "color": "#ffc72c",
        "icon": "🧳",
        "url": "https://www.expedia.com/Flight-Search?tripType=oneway&leg1=from:{dep_code}({dep}),to:{arr_code}({arr}),departure:{date}TANYT&passengers=adults:1",
    },
    # ── 国际航司官网 ──
    "jal": {
        "name": "日本航空 JAL",
        "color": "#e60012",
        "icon": "🇯🇵",
        "url": "https://www.jal.co.jp/jp/en/inter/?dep={dep_code}&arr={arr_code}&date={date}",
    },
    "ana": {
        "name": "全日空 ANA",
        "color": "#13448f",
        "icon": "🇯🇵",
        "url": "https://www.ana.co.jp/en/jp/?dep={dep_code}&arr={arr_code}&date={date}",
    },
    "koreanair": {
        "name": "大韩航空",
        "color": "#00256c",
        "icon": "🇰🇷",
        "url": "https://www.koreanair.com/jp/en/booking/booking-search?dep={dep_code}&arr={arr_code}&depDate={date}",
    },
    "singapore": {
        "name": "新加坡航空",
        "color": "#f99f1c",
        "icon": "🇸🇬",
        "url": "https://www.singaporeair.com/en_UK/jp/plan-book/flights/?dep={dep_code}&arr={arr_code}&date={date}",
    },
    "emirates": {
        "name": "阿联酋航空",
        "color": "#d71921",
        "icon": "🇦🇪",
        "url": "https://www.emirates.com/jp/english/book/flights/?dep={dep_code}&arr={arr_code}&date={date}",
    },
    "qatar": {
        "name": "卡塔尔航空",
        "color": "#5c0632",
        "icon": "🇶🇦",
        "url": "https://www.qatarairways.com/en/book/flights?dep={dep_code}&arr={arr_code}&date={date}",
    },
    "lufthansa": {
        "name": "汉莎航空",
        "color": "#05164d",
        "icon": "🇩🇪",
        "url": "https://www.lufthansa.com/online/portal/lh/jp/booking?dep={dep_code}&arr={arr_code}&date={date}",
    },
    "cathaypacific": {
        "name": "国泰航空",
        "color": "#006e63",
        "icon": "🇭🇰",
        "url": "https://www.cathaypacific.com/flights/jp/book?dep={dep_code}&arr={arr_code}&date={date}",
    },
    "airfrance": {
        "name": "法国航空",
        "color": "#002157",
        "icon": "🇫🇷",
        "url": "https://www.airfrance.com/search?dep={dep_code}&arr={arr_code}&depDate={date}",
    },
    "britishairways": {
        "name": "英国航空",
        "color": "#075aaa",
        "icon": "🇬🇧",
        "url": "https://www.britishairways.com/travel/home/public/en_us?dep={dep_code}&arr={arr_code}&date={date}",
    },
    "americanairlines": {
        "name": "美国航空",
        "color": "#0078d2",
        "icon": "🇺🇸",
        "url": "https://www.aa.com/booking/flights/search?dep={dep_code}&arr={arr_code}&depDate={date}",
    },
    "thaiairways": {
        "name": "泰国航空",
        "color": "#5d2e8c",
        "icon": "🇹🇭",
        "url": "https://www.thaiairways.com/en/booking/bookings.flights?dep={dep_code}&arr={arr_code}&date={date}",
    },
}

# ── Airline → Official Website mapping ────────────────────────
AIRLINE_OFFICIAL_SITES = {
    # 国内航司
    "中国国航": "airchina",
    "南方航空": "csair",
    "东方航空": "ceair",
    "海南航空": "hainan",
    "春秋航空": "spring",
    "吉祥航空": "juneyao",
    "深圳航空": "airchina",
    "厦门航空": "csair",
    "四川航空": "airchina",
    "山东航空": "airchina",
    "华夏航空": "airchina",
    "长龙航空": "airchina",
    "成都航空": "airchina",
    "首都航空": "hainan",
    "天津航空": "hainan",
    # 国际航司
    "日本航空": "jal",
    "全日空": "ana",
    "大韩航空": "koreanair",
    "韩亚航空": "koreanair",
    "新加坡航空": "singapore",
    "阿联酋航空": "emirates",
    "卡塔尔航空": "qatar",
    "汉莎航空": "lufthansa",
    "国泰航空": "cathaypacific",
    "港龙航空": "cathaypacific",
    "法国航空": "airfrance",
    "英国航空": "britishairways",
    "美国航空": "americanairlines",
    "达美航空": "americanairlines",
    "美联航": "americanairlines",
    "土耳其航空": "qatar",
    "泰国航空": "thaiairways",
    "马来西亚航空": "singapore",
    "越南航空": "singapore",
}

# Ctrip API
CTRIP_API_URL = "https://flights.ctrip.com/itinerary/api/12808/lowestPrice"
CTRIP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://flights.ctrip.com/",
    "Content-Type": "application/json",
}

# ── City codes (IATA codes) ───────────────────────────────────
# 国内城市
CITY_CODES = {
    # ── 中国大陆 ──
    "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
    "成都": "CTU", "杭州": "HGH", "武汉": "WUH", "西安": "XIY",
    "重庆": "CKG", "青岛": "TAO", "长沙": "CSX", "南京": "NKG",
    "厦门": "XMN", "昆明": "KMG", "大连": "DLC", "天津": "TSN",
    "郑州": "CGO", "三亚": "SYX", "海口": "HAK", "哈尔滨": "HRB",
    "沈阳": "SHE", "长春": "CGQ", "贵阳": "KWE", "南宁": "NNG",
    "兰州": "LHW", "乌鲁木齐": "URC", "拉萨": "LXA", "银川": "INC",
    "西宁": "XNN", "呼和浩特": "HET", "石家庄": "SJW", "太原": "TYN",
    "合肥": "HFE", "南昌": "KHN", "济南": "TNA", "福州": "FOC",
    "温州": "WNZ", "宁波": "NGB", "烟台": "YNT", "威海": "WEH",
    "珠海": "ZUH", "桂林": "KWL", "丽江": "LJG", "大理": "DLU",
    "敦煌": "DNH", "九寨沟": "JZH", "张家界": "DYG", "西双版纳": "JHG",
    "阿勒泰": "AAT", "喀什": "KHG", "伊宁": "YIN", "库尔勒": "KRL",
    "包头": "BAV", "鄂尔多斯": "DSN", "洛阳": "LYA", "南通": "NTG",
    "无锡": "WUX", "常州": "CZX", "徐州": "XUZ", "义乌": "YIW",
    "揭阳": "SWA", "湛江": "ZHA", "北海": "BHY", "黄山": "TXN",
    # ── 中国港澳台 ──
    "香港": "HKG", "澳门": "MFM", "台北": "TPE", "高雄": "KHH",
    # ── 日本 ──
    "东京": "TYO", "大阪": "OSA", "名古屋": "NGO", "福冈": "FUK",
    "札幌": "SPK", "冲绳": "OKA", "京都": "UKY",
    # ── 韩国 ──
    "首尔": "SEL", "釜山": "PUS", "济州岛": "CJU",
    # ── 东南亚 ──
    "新加坡": "SIN", "曼谷": "BKK", "吉隆坡": "KUL", "河内": "HAN",
    "胡志明市": "SGN", "雅加达": "CGK", "马尼拉": "MNL", "金边": "PNH",
    "仰光": "RGN", "巴厘岛": "DPS", "普吉岛": "HKT", "清迈": "CNX",
    "琅勃拉邦": "LPQ",
    # ── 中亚/南亚 ──
    "迪拜": "DXB", "多哈": "DOH", "德里": "DEL", "孟买": "BOM",
    "伊斯兰堡": "ISB", "塔什干": "TAS",
    # ── 欧洲 ──
    "伦敦": "LON", "巴黎": "PAR", "法兰克福": "FRA", "阿姆斯特丹": "AMS",
    "罗马": "ROM", "米兰": "MIL", "马德里": "MAD", "巴塞罗那": "BCN",
    "慕尼黑": "MUC", "柏林": "BER", "维也纳": "VIE", "苏黎世": "ZRH",
    "莫斯科": "MOW", "伊斯坦布尔": "IST", "雅典": "ATH",
    "哥本哈根": "CPH", "斯德哥尔摩": "STO", "都柏林": "DUB",
    "里斯本": "LIS", "赫尔辛基": "HEL",
    # ── 北美 ──
    "纽约": "NYC", "洛杉矶": "LAX", "旧金山": "SFO", "芝加哥": "ORD",
    "波士顿": "BOS", "华盛顿": "WAS", "西雅图": "SEA", "迈阿密": "MIA",
    "多伦多": "YTO", "温哥华": "YVR", "蒙特利尔": "YMQ",
    "拉斯维加斯": "LAS", "奥兰多": "MCO", "亚特兰大": "ATL",
    "达拉斯": "DFW", "休斯顿": "IAH",
    # ── 大洋洲 ──
    "悉尼": "SYD", "墨尔本": "MEL", "布里斯班": "BNE", "奥克兰": "AKL",
    "珀斯": "PER", "阿德莱德": "ADL",
    # ── 中东/非洲 ──
    "特拉维夫": "TLV", "开罗": "CAI", "约翰内斯堡": "JNB",
    "开普敦": "CPT", "内罗毕": "NBO", "亚的斯亚贝巴": "ADD",
    # ── 南美洲 ──
    "圣保罗": "SAO", "里约热内卢": "RIO", "布宜诺斯艾利斯": "BUE",
    "利马": "LIM", "圣地亚哥": "SCL",
}

# ── Airlines ──────────────────────────────────────────────────
# 国内航司（仅飞国内航线或国内出发的国际航线）
DOMESTIC_AIRLINES = [
    "中国国航", "南方航空", "东方航空", "海南航空", "深圳航空",
    "厦门航空", "四川航空", "山东航空", "春秋航空", "吉祥航空",
    "华夏航空", "长龙航空", "成都航空", "首都航空", "天津航空",
]

# 国际航司（仅飞国际航线）
INTERNATIONAL_AIRLINES = [
    "日本航空", "全日空", "大韩航空", "韩亚航空",
    "新加坡航空", "阿联酋航空", "卡塔尔航空", "汉莎航空",
    "国泰航空", "法国航空", "英国航空", "美国航空",
    "达美航空", "美联航", "土耳其航空", "泰国航空",
    "马来西亚航空", "越南航空",
]

# 合并列表（向后兼容）
AIRLINES = DOMESTIC_AIRLINES + INTERNATIONAL_AIRLINES

# ── International airline codes for flight number generation ──
AIRLINE_CODES_EXTRA = {
    "日本航空": "JL", "全日空": "NH", "大韩航空": "KE",
    "韩亚航空": "OZ", "新加坡航空": "SQ", "阿联酋航空": "EK",
    "卡塔尔航空": "QR", "汉莎航空": "LH", "国泰航空": "CX",
    "法国航空": "AF", "英国航空": "BA", "美国航空": "AA",
    "达美航空": "DL", "美联航": "UA", "土耳其航空": "TK",
    "泰国航空": "TG", "马来西亚航空": "MH", "越南航空": "VN",
}

# Aircraft types
AIRCRAFT_TYPES = [
    # 窄体机（短中程）
    "A320", "A321", "A319", "B737-800", "B738", "B737MAX",
    # 宽体机（中远程）
    "A330", "A332", "A333", "A350", "A359", "A35K",
    "B777", "B77W", "B787", "B789", "B747", "B748",
    # 支线/其他
    "E190", "E195", "ARJ21", "ATR72",
]

# ── Long-haul aircraft (for international routes) ─────────────
LONG_HAUL_AIRCRAFT = [
    "A330", "A332", "A333", "A350", "A359", "A35K",
    "B777", "B77W", "B787", "B789", "B747", "B748", "A380",
]

SHORT_HAUL_AIRCRAFT = [
    "A320", "A321", "A319", "B737-800", "B738", "B737MAX",
    "E190", "E195", "ARJ21",
]

# ── Route-Airline mapping for international routes ────────────
# Maps route regions to airlines that typically serve them
# Keys are (departure_region, arrival_region) tuples
# This ensures realistic airline selection per route
ROUTE_AIRLINES = {
    # China -> Japan
    ("中国大陆", "日韩"): ["中国国航", "东方航空", "南方航空", "日本航空", "全日空", "春秋航空", "吉祥航空"],
    ("港澳台", "日韩"): ["国泰航空", "日本航空", "全日空"],
    # China -> Korea
    ("中国大陆", "港澳台"): ["中国国航", "东方航空", "南方航空", "春秋航空", "厦门航空", "国泰航空"],
    # Japan -> Korea
    ("日韩", "日韩"): ["日本航空", "全日空", "大韩航空", "韩亚航空"],
    # China -> Southeast Asia
    ("中国大陆", "东南亚"): ["中国国航", "南方航空", "东方航空", "春秋航空", "四川航空", "泰国航空", "越南航空", "马来西亚航空", "新加坡航空"],
    # China -> Middle East
    ("中国大陆", "中东/南亚"): ["中国国航", "南方航空", "阿联酋航空", "卡塔尔航空"],
    # China -> Europe
    ("中国大陆", "欧洲"): ["中国国航", "东方航空", "汉莎航空", "法国航空", "英国航空"],
    # China -> North America
    ("中国大陆", "北美"): ["中国国航", "南方航空", "东方航空", "美国航空", "达美航空", "美联航"],
    # China -> Oceania
    ("中国大陆", "大洋洲"): ["中国国航", "南方航空", "东方航空"],
    # China -> Africa
    ("中国大陆", "中东/非洲"): ["中国国航", "南方航空", "阿联酋航空"],
    # China -> South America
    ("中国大陆", "南美洲"): ["中国国航", "美国航空", "达美航空"],
    # Southeast Asia internal
    ("东南亚", "东南亚"): ["新加坡航空", "泰国航空", "马来西亚航空", "越南航空"],
    # Europe internal
    ("欧洲", "欧洲"): ["法国航空", "英国航空", "汉莎航空"],
    # North America internal
    ("北美", "北美"): ["美国航空", "达美航空", "美联航"],
    # Transatlantic
    ("欧洲", "北美"): ["英国航空", "法国航空", "汉莎航空", "美国航空", "达美航空", "美联航"],
    ("北美", "欧洲"): ["英国航空", "法国航空", "汉莎航空", "美国航空", "达美航空", "美联航"],
    # Europe -> Asia
    ("欧洲", "日韩"): ["日本航空", "全日空", "汉莎航空", "法国航空", "英国航空"],
    ("欧洲", "东南亚"): ["新加坡航空", "泰国航空", "汉莎航空", "法国航空"],
    # North America -> Asia
    ("北美", "日韩"): ["日本航空", "全日空", "美国航空", "达美航空", "美联航"],
    ("北美", "东南亚"): ["新加坡航空", "美国航空", "达美航空"],
    # Oceania -> Asia
    ("大洋洲", "日韩"): ["日本航空", "全日空", "澳洲航空"],
    ("大洋洲", "东南亚"): ["新加坡航空", "泰国航空"],
    # Middle East hub
    ("中东/南亚", "欧洲"): ["阿联酋航空", "卡塔尔航空", "汉莎航空", "法国航空"],
    ("中东/南亚", "北美"): ["阿联酋航空", "卡塔尔航空", "美国航空"],
    ("中东/南亚", "东南亚"): ["阿联酋航空", "卡塔尔航空", "新加坡航空"],
}

# ── City to region mapping ────────────────────────────────────
# (defined after CITY_GROUPS, see below)
POPULAR_ROUTES = [
    # ── 国内热门 ──
    {"departure": "北京", "destination": "上海", "label": "京沪线"},
    {"departure": "北京", "destination": "广州", "label": "京广线"},
    {"departure": "北京", "destination": "成都", "label": "京蓉线"},
    {"departure": "北京", "destination": "三亚", "label": "京琼线"},
    {"departure": "上海", "destination": "广州", "label": "沪广线"},
    {"departure": "上海", "destination": "成都", "label": "沪蓉线"},
    {"departure": "广州", "destination": "成都", "label": "广蓉线"},
    {"departure": "深圳", "destination": "成都", "label": "深蓉线"},
    {"departure": "北京", "destination": "西安", "label": "京西线"},
    {"departure": "上海", "destination": "厦门", "label": "沪厦线"},
    {"departure": "广州", "destination": "海口", "label": "广琼线"},
    {"departure": "成都", "destination": "拉萨", "label": "川藏线"},
    # ── 港澳台 ──
    {"departure": "北京", "destination": "香港", "label": "京港线"},
    {"departure": "上海", "destination": "香港", "label": "沪港线"},
    {"departure": "深圳", "destination": "香港", "label": "深港线"},
    {"departure": "厦门", "destination": "台北", "label": "厦台线"},
    # ── 日韩 ──
    {"departure": "北京", "destination": "东京", "label": "京东线"},
    {"departure": "上海", "destination": "东京", "label": "沪东线"},
    {"departure": "上海", "destination": "大阪", "label": "沪阪线"},
    {"departure": "北京", "destination": "首尔", "label": "京韩线"},
    {"departure": "上海", "destination": "首尔", "label": "沪韩线"},
    {"departure": "上海", "destination": "济州岛", "label": "沪济线"},
    # ── 东南亚 ──
    {"departure": "北京", "destination": "曼谷", "label": "京泰线"},
    {"departure": "上海", "destination": "曼谷", "label": "沪泰线"},
    {"departure": "广州", "destination": "曼谷", "label": "广泰线"},
    {"departure": "广州", "destination": "新加坡", "label": "广新线"},
    {"departure": "成都", "destination": "新加坡", "label": "蓉新线"},
    {"departure": "上海", "destination": "巴厘岛", "label": "沪巴线"},
    {"departure": "广州", "destination": "胡志明市", "label": "广越线"},
    {"departure": "昆明", "destination": "清迈", "label": "昆清线"},
    # ── 中东 ──
    {"departure": "北京", "destination": "迪拜", "label": "京迪线"},
    {"departure": "上海", "destination": "迪拜", "label": "沪迪线"},
    {"departure": "广州", "destination": "多哈", "label": "广卡线"},
    # ── 欧洲 ──
    {"departure": "北京", "destination": "伦敦", "label": "京伦线"},
    {"departure": "上海", "destination": "伦敦", "label": "沪伦线"},
    {"departure": "北京", "destination": "巴黎", "label": "京巴线"},
    {"departure": "上海", "destination": "巴黎", "label": "沪巴线"},
    {"departure": "北京", "destination": "法兰克福", "label": "京法线"},
    {"departure": "上海", "destination": "法兰克福", "label": "沪法线"},
    {"departure": "广州", "destination": "伊斯坦布尔", "label": "广伊线"},
    # ── 北美 ──
    {"departure": "北京", "destination": "纽约", "label": "京纽线"},
    {"departure": "上海", "destination": "纽约", "label": "沪纽线"},
    {"departure": "北京", "destination": "洛杉矶", "label": "京洛线"},
    {"departure": "上海", "destination": "洛杉矶", "label": "沪洛线"},
    {"departure": "北京", "destination": "旧金山", "label": "京旧线"},
    {"departure": "香港", "destination": "旧金山", "label": "港旧线"},
    # ── 大洋洲 ──
    {"departure": "北京", "destination": "悉尼", "label": "京悉线"},
    {"departure": "上海", "destination": "悉尼", "label": "沪悉线"},
    {"departure": "广州", "destination": "墨尔本", "label": "广墨线"},
    # ── 区域内国际 ──
    {"departure": "东京", "destination": "首尔", "label": "日韩线"},
    {"departure": "东京", "destination": "曼谷", "label": "日泰线"},
    {"departure": "首尔", "destination": "曼谷", "label": "韩泰线"},
    {"departure": "新加坡", "destination": "巴厘岛", "label": "新巴线"},
    {"departure": "伦敦", "destination": "巴黎", "label": "欧内线"},
    {"departure": "纽约", "destination": "洛杉矶", "label": "美内线"},
    {"departure": "纽约", "destination": "伦敦", "label": "跨大西洋"},
]

# ── International city groups for UI grouping ─────────────────
CITY_GROUPS = {
    "中国大陆": [
        "北京", "上海", "广州", "深圳", "成都", "杭州", "武汉", "西安",
        "重庆", "青岛", "长沙", "南京", "厦门", "昆明", "大连", "天津",
        "郑州", "三亚", "海口", "哈尔滨", "沈阳", "长春", "贵阳", "南宁",
        "兰州", "乌鲁木齐", "拉萨", "银川", "西宁", "呼和浩特", "石家庄",
        "太原", "合肥", "南昌", "济南", "福州", "温州", "宁波", "烟台",
        "威海", "珠海", "桂林", "丽江", "大理", "敦煌", "九寨沟",
        "张家界", "西双版纳", "阿勒泰", "喀什", "伊宁", "库尔勒",
        "包头", "鄂尔多斯", "洛阳", "南通", "无锡", "常州", "徐州",
        "义乌", "揭阳", "湛江", "北海", "黄山",
    ],
    "港澳台": ["香港", "澳门", "台北", "高雄"],
    "日韩": ["东京", "大阪", "名古屋", "福冈", "札幌", "冲绳", "京都", "首尔", "釜山", "济州岛"],
    "东南亚": [
        "新加坡", "曼谷", "吉隆坡", "河内", "胡志明市", "雅加达", "马尼拉",
        "金边", "仰光", "巴厘岛", "普吉岛", "清迈", "琅勃拉邦",
    ],
    "中东/南亚": ["迪拜", "多哈", "德里", "孟买", "伊斯兰堡", "塔什干"],
    "欧洲": [
        "伦敦", "巴黎", "法兰克福", "阿姆斯特丹", "罗马", "米兰", "马德里",
        "巴塞罗那", "慕尼黑", "柏林", "维也纳", "苏黎世", "莫斯科",
        "伊斯坦布尔", "雅典", "哥本哈根", "斯德哥尔摩", "都柏林",
        "里斯本", "赫尔辛基",
    ],
    "北美": [
        "纽约", "洛杉矶", "旧金山", "芝加哥", "波士顿", "华盛顿", "西雅图",
        "迈阿密", "多伦多", "温哥华", "蒙特利尔", "拉斯维加斯", "奥兰多",
        "亚特兰大", "达拉斯", "休斯顿",
    ],
    "大洋洲": ["悉尼", "墨尔本", "布里斯班", "奥克兰", "珀斯", "阿德莱德"],
    "中东/非洲": ["特拉维夫", "开罗", "约翰内斯堡", "开普敦", "内罗毕", "亚的斯亚贝巴"],
    "南美洲": ["圣保罗", "里约热内卢", "布宜诺斯艾利斯", "利马", "圣地亚哥"],
}

# ── City to region mapping (must be after CITY_GROUPS) ───────
CITY_TO_REGION = {}
for _region, _cities in CITY_GROUPS.items():
    for _city in _cities:
        CITY_TO_REGION[_city] = _region
