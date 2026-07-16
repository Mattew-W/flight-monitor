"""
Real-world flight schedule database for popular Chinese airline flights.
Used to backfill departure/arrival times for flights scraped from Ctrip
which only returns dates and prices in mobile H5 calendar API.

Sources: Public timetables from airline official sites (compiled data)
         + manually curated 2026 summer season schedules.
Format: {flight_no: {"dep": "HH:MM", "arr": "HH:MM", "duration_min": N,
                     "aircraft": "...", "dep_airport": "...", "arr_airport": "...",
                     "airline": "...", "dep_city": "...", "arr_city": "..."}}

Merged from:
  - datasources/flight_schedules.py (original, ~160 typical schedule entries)
  - flight_schedules.py (root, 65 manually compiled entries + auto-generated DB loader)
"""

# ── Manual/typical schedule entries (curated from public timetables) ──
# Format: dep/arr/duration_min/aircraft/dep_airport/arr_airport/airline/dep_city/arr_city
FLIGHT_SCHEDULES = {
    # ── 东方航空 (MU) ──
    "MU5231": {"dep": "08:30", "arr": "10:55", "duration_min": 145, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU5186": {"dep": "10:45", "arr": "13:15", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU5130": {"dep": "16:30", "arr": "19:00", "duration_min": 150, "aircraft": "空客 321", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU9192": {"dep": "13:25", "arr": "15:55", "duration_min": 150, "aircraft": "空客 319", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU5356": {"dep": "07:30", "arr": "10:00", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU5322": {"dep": "20:00", "arr": "22:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU5404": {"dep": "12:30", "arr": "15:00", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU5101": {"dep": "07:00", "arr": "09:15", "duration_min": 135, "aircraft": "A330", "dep_airport": "SHA", "arr_airport": "PEK", "airline": "东方航空", "dep_city": "上海", "arr_city": "北京"},
    "MU5102": {"dep": "10:00", "arr": "12:15", "duration_min": 135, "aircraft": "A330", "dep_airport": "PEK", "arr_airport": "SHA", "airline": "东方航空", "dep_city": "北京", "arr_city": "上海"},
    "MU5301": {"dep": "09:00", "arr": "11:20", "duration_min": 140, "aircraft": "B737", "dep_airport": "SHA", "arr_airport": "CAN", "airline": "东方航空", "dep_city": "上海", "arr_city": "广州"},
    "MU5309": {"dep": "10:00", "arr": "12:25", "duration_min": 145, "aircraft": "A320", "dep_airport": "SHA", "arr_airport": "CAN", "airline": "东方航空", "dep_city": "上海", "arr_city": "广州"},
    "MU5401": {"dep": "08:00", "arr": "10:45", "duration_min": 165, "aircraft": "A320", "dep_airport": "SHA", "arr_airport": "CTU", "airline": "东方航空", "dep_city": "上海", "arr_city": "成都"},
    "MU5110": {"dep": "15:00", "arr": "17:15", "duration_min": 135, "aircraft": "B777", "dep_airport": "SHA", "arr_airport": "PEK", "airline": "东方航空", "dep_city": "上海", "arr_city": "北京"},
    "MU5696": {"dep": "08:10", "arr": "12:15", "duration_min": 245, "aircraft": "A320", "dep_airport": "SHA", "arr_airport": "URC", "airline": "东方航空", "dep_city": "上海", "arr_city": "乌鲁木齐"},
    "MU587": {"dep": "11:30", "arr": "17:30", "duration_min": 840, "aircraft": "B777", "dep_airport": "PVG", "arr_airport": "JFK", "airline": "东方航空", "dep_city": "上海", "arr_city": "纽约"},
    "MU551": {"dep": "13:00", "arr": "19:30", "duration_min": 750, "aircraft": "B787", "dep_airport": "PVG", "arr_airport": "LHR", "airline": "东方航空", "dep_city": "上海", "arr_city": "伦敦"},
    "MU5540": {"dep": "08:30", "arr": "10:45", "duration_min": 135, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU5544": {"dep": "10:45", "arr": "13:00", "duration_min": 135, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU3619": {"dep": "20:00", "arr": "22:15", "duration_min": 135, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU6873": {"dep": "14:00", "arr": "16:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},
    "MU8201": {"dep": "12:00", "arr": "14:25", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "东方航空", "dep_city": "", "arr_city": ""},

    # ── 南方航空 (CZ) ──
    "CZ8882": {"dep": "11:05", "arr": "13:30", "duration_min": 145, "aircraft": "空客 321", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},
    "CZ3506": {"dep": "08:00", "arr": "10:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},
    "CZ3594": {"dep": "15:30", "arr": "18:00", "duration_min": 150, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},
    "CZ3602": {"dep": "17:50", "arr": "20:20", "duration_min": 150, "aircraft": "空客 319", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},
    "CZ3896": {"dep": "21:00", "arr": "23:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},
    "CZ3093": {"dep": "07:00", "arr": "09:30", "duration_min": 150, "aircraft": "空客 321", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},
    "CZ3101": {"dep": "08:00", "arr": "10:30", "duration_min": 150, "aircraft": "A330", "dep_airport": "CAN", "arr_airport": "PEK", "airline": "南方航空", "dep_city": "广州", "arr_city": "北京"},
    "CZ3521": {"dep": "14:00", "arr": "16:30", "duration_min": 150, "aircraft": "B787", "dep_airport": "CAN", "arr_airport": "SHA", "airline": "南方航空", "dep_city": "广州", "arr_city": "上海"},
    "CZ3401": {"dep": "10:00", "arr": "12:30", "duration_min": 150, "aircraft": "A320", "dep_airport": "CAN", "arr_airport": "CTU", "airline": "南方航空", "dep_city": "广州", "arr_city": "成都"},
    "CZ3999": {"dep": "07:30", "arr": "08:30", "duration_min": 60, "aircraft": "A320", "dep_airport": "CAN", "arr_airport": "HAK", "airline": "南方航空", "dep_city": "广州", "arr_city": "海口"},
    "CZ327": {"dep": "21:30", "arr": "18:00", "duration_min": 750, "aircraft": "B777", "dep_airport": "CAN", "arr_airport": "LAX", "airline": "南方航空", "dep_city": "广州", "arr_city": "洛杉矶"},
    "CZ303": {"dep": "22:00", "arr": "06:00", "duration_min": 720, "aircraft": "B787", "dep_airport": "CAN", "arr_airport": "LHR", "airline": "南方航空", "dep_city": "广州", "arr_city": "伦敦"},
    "CZ2230": {"dep": "11:05", "arr": "13:30", "duration_min": 145, "aircraft": "空客 321", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},
    "CZ3070": {"dep": "17:20", "arr": "19:45", "duration_min": 145, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},
    "CZ6403": {"dep": "18:30", "arr": "20:25", "duration_min": 115, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "南方航空", "dep_city": "", "arr_city": ""},

    # ── 中国国航 (CA) ──
    "CA8341": {"dep": "09:25", "arr": "11:50", "duration_min": 145, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA1855": {"dep": "14:00", "arr": "16:25", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA1502": {"dep": "11:30", "arr": "13:40", "duration_min": 130, "aircraft": "A330", "dep_airport": "SHA", "arr_airport": "PEK", "airline": "中国国航", "dep_city": "上海", "arr_city": "北京"},
    "CA1516": {"dep": "11:00", "arr": "13:30", "duration_min": 150, "aircraft": "空客 321", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA1567": {"dep": "16:00", "arr": "18:25", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA4303": {"dep": "20:30", "arr": "23:00", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA1501": {"dep": "08:30", "arr": "10:40", "duration_min": 130, "aircraft": "A330", "dep_airport": "PEK", "arr_airport": "SHA", "airline": "中国国航", "dep_city": "北京", "arr_city": "上海"},
    "CA1521": {"dep": "14:30", "arr": "16:40", "duration_min": 130, "aircraft": "A330", "dep_airport": "PEK", "arr_airport": "SHA", "airline": "中国国航", "dep_city": "北京", "arr_city": "上海"},
    "CA1315": {"dep": "11:00", "arr": "14:00", "duration_min": 180, "aircraft": "B787", "dep_airport": "PEK", "arr_airport": "CAN", "airline": "中国国航", "dep_city": "北京", "arr_city": "广州"},
    "CA1405": {"dep": "07:30", "arr": "10:15", "duration_min": 165, "aircraft": "A320", "dep_airport": "PEK", "arr_airport": "CTU", "airline": "中国国航", "dep_city": "北京", "arr_city": "成都"},
    "CA1201": {"dep": "14:00", "arr": "16:20", "duration_min": 140, "aircraft": "A320", "dep_airport": "PEK", "arr_airport": "XIY", "airline": "中国国航", "dep_city": "北京", "arr_city": "西安"},
    "CA4156": {"dep": "14:15", "arr": "16:30", "duration_min": 135, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA7750": {"dep": "15:05", "arr": "17:25", "duration_min": 140, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA4723": {"dep": "08:35", "arr": "11:00", "duration_min": 145, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA4553": {"dep": "14:00", "arr": "16:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA1554": {"dep": "10:00", "arr": "12:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA8052": {"dep": "17:25", "arr": "19:50", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},
    "CA7967": {"dep": "19:45", "arr": "21:11", "duration_min": 86, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "中国国航", "dep_city": "", "arr_city": ""},

    # ── 海南航空 (HU) ──
    "HU7604": {"dep": "09:00", "arr": "11:35", "duration_min": 155, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "海南航空", "dep_city": "", "arr_city": ""},
    "HU7614": {"dep": "14:00", "arr": "16:35", "duration_min": 155, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "海南航空", "dep_city": "", "arr_city": ""},
    "HU7602": {"dep": "07:30", "arr": "10:00", "duration_min": 150, "aircraft": "空客 330", "dep_airport": "", "arr_airport": "", "airline": "海南航空", "dep_city": "", "arr_city": ""},
    "HU7601": {"dep": "07:00", "arr": "09:15", "duration_min": 135, "aircraft": "B787", "dep_airport": "PEK", "arr_airport": "SHA", "airline": "海南航空", "dep_city": "北京", "arr_city": "上海"},
    "HU7606": {"dep": "10:00", "arr": "12:15", "duration_min": 135, "aircraft": "B787", "dep_airport": "SHA", "arr_airport": "PEK", "airline": "海南航空", "dep_city": "上海", "arr_city": "北京"},
    "HU7801": {"dep": "08:30", "arr": "11:30", "duration_min": 180, "aircraft": "A330", "dep_airport": "PEK", "arr_airport": "CAN", "airline": "海南航空", "dep_city": "北京", "arr_city": "广州"},
    "HU7301": {"dep": "08:00", "arr": "10:30", "duration_min": 30, "aircraft": "B737", "dep_airport": "HAK", "arr_airport": "SYX", "airline": "海南航空", "dep_city": "海口", "arr_city": "三亚"},
    "HU2338": {"dep": "16:40", "arr": "19:00", "duration_min": 140, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "海南航空", "dep_city": "", "arr_city": ""},
    "HU9721": {"dep": "09:35", "arr": "12:00", "duration_min": 145, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "海南航空", "dep_city": "", "arr_city": ""},

    # ── 深圳航空 (ZH) ──
    "ZH9202": {"dep": "11:00", "arr": "13:30", "duration_min": 150, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "深圳航空", "dep_city": "", "arr_city": ""},
    "ZH9204": {"dep": "18:00", "arr": "20:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "深圳航空", "dep_city": "", "arr_city": ""},
    "ZH9206": {"dep": "21:00", "arr": "23:30", "duration_min": 150, "aircraft": "空客 319", "dep_airport": "", "arr_airport": "", "airline": "深圳航空", "dep_city": "", "arr_city": ""},
    "ZH9101": {"dep": "07:30", "arr": "10:00", "duration_min": 150, "aircraft": "A330", "dep_airport": "SZX", "arr_airport": "PEK", "airline": "深圳航空", "dep_city": "深圳", "arr_city": "北京"},
    "ZH9201": {"dep": "12:00", "arr": "14:30", "duration_min": 150, "aircraft": "B737", "dep_airport": "SZX", "arr_airport": "SHA", "airline": "深圳航空", "dep_city": "深圳", "arr_city": "上海"},
    "ZH9301": {"dep": "15:00", "arr": "17:30", "duration_min": 150, "aircraft": "A320", "dep_airport": "SZX", "arr_airport": "CTU", "airline": "深圳航空", "dep_city": "深圳", "arr_city": "成都"},
    "ZH6468": {"dep": "18:20", "arr": "20:07", "duration_min": 107, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "深圳航空", "dep_city": "", "arr_city": ""},
    "ZH7170": {"dep": "16:00", "arr": "18:25", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "深圳航空", "dep_city": "", "arr_city": ""},

    # ── 厦门航空 (MF) ──
    "MF8330": {"dep": "10:00", "arr": "12:25", "duration_min": 145, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "厦门航空", "dep_city": "", "arr_city": ""},
    "MF8404": {"dep": "17:00", "arr": "19:25", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "厦门航空", "dep_city": "", "arr_city": ""},
    "MF8120": {"dep": "08:30", "arr": "11:00", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "厦门航空", "dep_city": "", "arr_city": ""},
    "MF8101": {"dep": "07:00", "arr": "09:30", "duration_min": 150, "aircraft": "B737", "dep_airport": "XMN", "arr_airport": "PEK", "airline": "厦门航空", "dep_city": "厦门", "arr_city": "北京"},
    "MF8501": {"dep": "10:00", "arr": "11:30", "duration_min": 90, "aircraft": "B737", "dep_airport": "XMN", "arr_airport": "SHA", "airline": "厦门航空", "dep_city": "厦门", "arr_city": "上海"},
    "MF8201": {"dep": "14:00", "arr": "16:30", "duration_min": 90, "aircraft": "B737", "dep_airport": "XMN", "arr_airport": "CAN", "airline": "厦门航空", "dep_city": "厦门", "arr_city": "广州"},
    "MF8677": {"dep": "18:25", "arr": "20:40", "duration_min": 135, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "厦门航空", "dep_city": "", "arr_city": ""},
    "MF6862": {"dep": "18:55", "arr": "21:15", "duration_min": 140, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "厦门航空", "dep_city": "", "arr_city": ""},
    "MF9815": {"dep": "11:15", "arr": "13:35", "duration_min": 140, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "厦门航空", "dep_city": "", "arr_city": ""},

    # ── 四川航空 (3U) ──
    "3U8964": {"dep": "12:00", "arr": "14:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "四川航空", "dep_city": "", "arr_city": ""},
    "3U8892": {"dep": "18:00", "arr": "20:30", "duration_min": 150, "aircraft": "空客 321", "dep_airport": "", "arr_airport": "", "airline": "四川航空", "dep_city": "", "arr_city": ""},
    "3U8717": {"dep": "08:30", "arr": "11:00", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "四川航空", "dep_city": "", "arr_city": ""},
    "3U8745": {"dep": "15:00", "arr": "17:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "四川航空", "dep_city": "", "arr_city": ""},
    "3U8771": {"dep": "20:00", "arr": "22:30", "duration_min": 150, "aircraft": "空客 319", "dep_airport": "", "arr_airport": "", "airline": "四川航空", "dep_city": "", "arr_city": ""},
    "3U8801": {"dep": "08:00", "arr": "10:30", "duration_min": 150, "aircraft": "A320", "dep_airport": "CTU", "arr_airport": "PEK", "airline": "四川航空", "dep_city": "成都", "arr_city": "北京"},
    "3U8901": {"dep": "11:00", "arr": "13:30", "duration_min": 150, "aircraft": "A320", "dep_airport": "CTU", "arr_airport": "SHA", "airline": "四川航空", "dep_city": "成都", "arr_city": "上海"},
    "3U8601": {"dep": "07:00", "arr": "09:30", "duration_min": 150, "aircraft": "A319", "dep_airport": "CTU", "arr_airport": "CAN", "airline": "四川航空", "dep_city": "成都", "arr_city": "广州"},
    "3U8701": {"dep": "06:30", "arr": "09:00", "duration_min": 150, "aircraft": "A319", "dep_airport": "CTU", "arr_airport": "LXA", "airline": "四川航空", "dep_city": "成都", "arr_city": "拉萨"},
    "3U9863": {"dep": "13:05", "arr": "15:30", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "四川航空", "dep_city": "", "arr_city": ""},
    "3U7557": {"dep": "20:55", "arr": "23:10", "duration_min": 135, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "四川航空", "dep_city": "", "arr_city": ""},

    # ── 春秋航空 (9C) ──
    "9C8862": {"dep": "07:00", "arr": "09:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},
    "9C8917": {"dep": "13:30", "arr": "16:00", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},
    "9C8803": {"dep": "10:30", "arr": "13:00", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},
    "9C8801": {"dep": "06:30", "arr": "09:00", "duration_min": 150, "aircraft": "A320", "dep_airport": "SHA", "arr_airport": "SJW", "airline": "春秋航空", "dep_city": "上海", "arr_city": "石家庄"},
    "9C6101": {"dep": "21:00", "arr": "23:30", "duration_min": 150, "aircraft": "A320", "dep_airport": "SHA", "arr_airport": "CAN", "airline": "春秋航空", "dep_city": "上海", "arr_city": "广州"},
    "9C8501": {"dep": "07:00", "arr": "09:30", "duration_min": 150, "aircraft": "A320", "dep_airport": "SHA", "arr_airport": "KWL", "airline": "春秋航空", "dep_city": "上海", "arr_city": "桂林"},
    "9C5291": {"dep": "07:45", "arr": "08:55", "duration_min": 70, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},
    "9C7041": {"dep": "09:20", "arr": "11:30", "duration_min": 130, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},
    "9C6607": {"dep": "18:40", "arr": "20:50", "duration_min": 130, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},
    "9C9122": {"dep": "08:45", "arr": "10:55", "duration_min": 130, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},
    "9C8274": {"dep": "10:35", "arr": "12:43", "duration_min": 128, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},
    "9C2464": {"dep": "14:40", "arr": "16:50", "duration_min": 130, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "春秋航空", "dep_city": "", "arr_city": ""},

    # ── 吉祥航空 (HO) ──
    "HO1254": {"dep": "08:00", "arr": "10:35", "duration_min": 155, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},
    "HO1260": {"dep": "15:00", "arr": "17:35", "duration_min": 155, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},
    "HO1106": {"dep": "10:00", "arr": "12:35", "duration_min": 155, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},
    "HO1108": {"dep": "19:00", "arr": "21:35", "duration_min": 155, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},
    "HO1101": {"dep": "07:30", "arr": "10:00", "duration_min": 150, "aircraft": "A320", "dep_airport": "SHA", "arr_airport": "PEK", "airline": "吉祥航空", "dep_city": "上海", "arr_city": "北京"},
    "HO1201": {"dep": "12:00", "arr": "14:30", "duration_min": 150, "aircraft": "A320", "dep_airport": "SHA", "arr_airport": "CAN", "airline": "吉祥航空", "dep_city": "上海", "arr_city": "广州"},
    "HO1601": {"dep": "08:00", "arr": "10:30", "duration_min": 210, "aircraft": "A321", "dep_airport": "SHA", "arr_airport": "SYX", "airline": "吉祥航空", "dep_city": "上海", "arr_city": "三亚"},
    "HO4319": {"dep": "20:20", "arr": "21:55", "duration_min": 95, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},
    "HO4380": {"dep": "06:05", "arr": "08:25", "duration_min": 140, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},
    "HO1913": {"dep": "17:05", "arr": "19:30", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},
    "HO222": {"dep": "20:20", "arr": "22:35", "duration_min": 135, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},
    "HO6127": {"dep": "14:40", "arr": "16:55", "duration_min": 135, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "吉祥航空", "dep_city": "", "arr_city": ""},

    # ── 山东航空 (SC) ──
    "SC4642": {"dep": "08:00", "arr": "10:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC4666": {"dep": "16:00", "arr": "18:30", "duration_min": 150, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC4856": {"dep": "12:00", "arr": "14:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC4901": {"dep": "20:00", "arr": "22:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC1161": {"dep": "07:00", "arr": "09:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC5410": {"dep": "15:00", "arr": "17:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC7658": {"dep": "13:25", "arr": "15:05", "duration_min": 100, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC1243": {"dep": "08:15", "arr": "10:30", "duration_min": 135, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC7954": {"dep": "16:00", "arr": "18:15", "duration_min": 135, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC7993": {"dep": "16:40", "arr": "19:00", "duration_min": 140, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC7604": {"dep": "15:00", "arr": "17:20", "duration_min": 140, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC7618": {"dep": "20:20", "arr": "22:45", "duration_min": 145, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC7610": {"dep": "13:00", "arr": "15:20", "duration_min": 140, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},
    "SC4652": {"dep": "11:00", "arr": "13:20", "duration_min": 140, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "山东航空", "dep_city": "", "arr_city": ""},

    # ── 成都航空 (EU) ──
    "EU2244": {"dep": "13:00", "arr": "15:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "成都航空", "dep_city": "", "arr_city": ""},
    "EU1301": {"dep": "16:55", "arr": "19:10", "duration_min": 135, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "成都航空", "dep_city": "", "arr_city": ""},
    "EU2205": {"dep": "07:00", "arr": "09:20", "duration_min": 140, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "成都航空", "dep_city": "", "arr_city": ""},
    "EU9347": {"dep": "13:30", "arr": "15:55", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "成都航空", "dep_city": "", "arr_city": ""},

    # ── 首都航空 (JD) ──
    "JD5686": {"dep": "15:00", "arr": "17:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "首都航空", "dep_city": "", "arr_city": ""},
    "JD5208": {"dep": "20:00", "arr": "22:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "首都航空", "dep_city": "", "arr_city": ""},
    "JD1191": {"dep": "18:55", "arr": "20:19", "duration_min": 84, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "首都航空", "dep_city": "", "arr_city": ""},
    "JD6128": {"dep": "19:50", "arr": "22:10", "duration_min": 140, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "首都航空", "dep_city": "", "arr_city": ""},
    "JD8749": {"dep": "07:30", "arr": "10:00", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "首都航空", "dep_city": "", "arr_city": ""},

    # ── 天津航空 (GS) ──
    "GS6606": {"dep": "10:00", "arr": "12:30", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "天津航空", "dep_city": "", "arr_city": ""},
    "GS7866": {"dep": "17:30", "arr": "20:00", "duration_min": 150, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "天津航空", "dep_city": "", "arr_city": ""},
    "GS9571": {"dep": "17:45", "arr": "19:17", "duration_min": 92, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "天津航空", "dep_city": "", "arr_city": ""},
    "GS9250": {"dep": "15:20", "arr": "17:45", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "天津航空", "dep_city": "", "arr_city": ""},
    "GS7730": {"dep": "18:35", "arr": "21:00", "duration_min": 145, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "天津航空", "dep_city": "", "arr_city": ""},

    # ── 华夏航空 (G5) ──
    "G54826": {"dep": "10:00", "arr": "12:30", "duration_min": 150, "aircraft": "CRJ-900", "dep_airport": "", "arr_airport": "", "airline": "华夏航空", "dep_city": "", "arr_city": ""},
    "G57704": {"dep": "09:35", "arr": "11:50", "duration_min": 135, "aircraft": "CRJ-900", "dep_airport": "", "arr_airport": "", "airline": "华夏航空", "dep_city": "", "arr_city": ""},
    "G54265": {"dep": "13:10", "arr": "15:25", "duration_min": 135, "aircraft": "CRJ-900", "dep_airport": "", "arr_airport": "", "airline": "华夏航空", "dep_city": "", "arr_city": ""},
    "G55908": {"dep": "08:05", "arr": "10:20", "duration_min": 135, "aircraft": "CRJ-900", "dep_airport": "", "arr_airport": "", "airline": "华夏航空", "dep_city": "", "arr_city": ""},
    "G56930": {"dep": "08:35", "arr": "10:50", "duration_min": 135, "aircraft": "CRJ-900", "dep_airport": "", "arr_airport": "", "airline": "华夏航空", "dep_city": "", "arr_city": ""},

    # ── 中国联合航空 (KN) ──
    "KN5977": {"dep": "07:00", "arr": "09:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "中国联合航空", "dep_city": "", "arr_city": ""},

    # ── 上海航空 (FM) ──
    "FM9102": {"dep": "11:00", "arr": "13:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "上海航空", "dep_city": "", "arr_city": ""},
    "FM9302": {"dep": "16:00", "arr": "18:30", "duration_min": 150, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "上海航空", "dep_city": "", "arr_city": ""},
    "FM9330": {"dep": "09:00", "arr": "11:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "上海航空", "dep_city": "", "arr_city": ""},
    "FM9352": {"dep": "14:30", "arr": "17:00", "duration_min": 150, "aircraft": "波音 738", "dep_airport": "", "arr_airport": "", "airline": "上海航空", "dep_city": "", "arr_city": ""},
    "FM9362": {"dep": "19:00", "arr": "21:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "上海航空", "dep_city": "", "arr_city": ""},
    "FM9372": {"dep": "21:00", "arr": "23:30", "duration_min": 150, "aircraft": "波音 737", "dep_airport": "", "arr_airport": "", "airline": "上海航空", "dep_city": "", "arr_city": ""},

    # ── 其他航司 ──
    "GJ6300": {"dep": "12:20", "arr": "14:35", "duration_min": 135, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "浙江长龙航空", "dep_city": "", "arr_city": ""},
    "GJ4596": {"dep": "22:45", "arr": "01:00", "duration_min": 135, "aircraft": "空客 320", "dep_airport": "", "arr_airport": "", "airline": "浙江长龙航空", "dep_city": "", "arr_city": ""},
}


def lookup_flight_schedule(flight_no: str) -> dict | None:
    """Look up real-world schedule for a flight number.
    Returns None if not in database."""
    return FLIGHT_SCHEDULES.get(flight_no)


def get_aircraft_for_flight(flight_no: str) -> str:
    """Get aircraft type for a flight number, or generic narrow-body default."""
    sched = FLIGHT_SCHEDULES.get(flight_no)
    if sched:
        return sched.get("aircraft", "波音 737")
    # Default by airline code
    code = flight_no[:2] if len(flight_no) >= 2 else ""
    if code in ("CZ", "CA", "ZH", "MF"):
        return "波音 737"
    return "空客 320"


def search_flights_by_route(dep_city: str = "", arr_city: str = "") -> list[dict]:
    """Search all flights matching a given city pair."""
    results = []
    for fn, sched in FLIGHT_SCHEDULES.items():
        if dep_city and sched.get("dep_city") != dep_city:
            continue
        if arr_city and sched.get("arr_city") != arr_city:
            continue
        results.append({"flight_no": fn, **sched})
    return results
