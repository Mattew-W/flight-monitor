"""
Flight Monitor - Skyscanner Data Source (No Browser!)
Uses Skyscanner public browse API via curl_cffi.
No Playwright, no Chrome, pure HTTP requests.
"""
import logging
import time
import random
from datetime import datetime
from typing import List

from .base import BaseDataSource, register_source
from .skyscanner_client import search_flights_skyscanner
from core.models import FlightPrice, SearchQuery

logger = logging.getLogger(__name__)

_skyscanner_available = True  # built-in client, no external dependency


# ── City → IATA code mapping (major hubs) ────────────────────────
CITY_TO_IATA = {
    "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
    "成都": "CTU", "杭州": "HGH", "武汉": "WUH", "西安": "XIY",
    "重庆": "CKG", "青岛": "TAO", "长沙": "CSX", "南京": "NKG",
    "厦门": "XMN", "昆明": "KMG", "大连": "DLC", "天津": "TSN",
    "郑州": "CGO", "三亚": "SYX", "海口": "HAK", "哈尔滨": "HRB",
    "沈阳": "SHE", "贵阳": "KWE", "南宁": "NNG", "兰州": "LHW",
    "乌鲁木齐": "URC", "拉萨": "LXA",
    "香港": "HKG", "台北": "TPE",
    "东京": "TYO", "大阪": "OSA", "首尔": "SEL",
    "新加坡": "SIN", "曼谷": "BKK", "吉隆坡": "KUL",
    "迪拜": "DXB",
    "伦敦": "LON", "巴黎": "PAR", "法兰克福": "FRA",
    "纽约": "NYC", "洛杉矶": "LAX", "旧金山": "SFO",
    "悉尼": "SYD", "墨尔本": "MEL",
}


@register_source("skyscanner")
class SkyscannerSource(BaseDataSource):
    """Skyscanner data source via public browse API.

    Uses pure HTTP requests (no browser) to call Skyscanner's browse
    endpoint. Much faster than Playwright and less likely to be rate-limited.
    """

    name = "skyscanner"

    def __init__(self):
        pass

    def is_available(self) -> bool:
        return _skyscanner_available

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        if not self.is_available():
            return []

        # Small random delay
        time.sleep(random.uniform(0.3, 1.5))

        try:
            raw = search_flights_skyscanner(
                dep=query.departure,
                arr=query.destination,
                date=query.departure_date,
                cabin=query.cabin_class or "economy",
            )

            results = []
            now = datetime.now().isoformat()
            for item in raw:
                duration = ""
                dm = item.get("duration_min", 0)
                if dm:
                    duration = f"{dm // 60}h{dm % 60}m"
                results.append(FlightPrice(
                    query_id=query.id or 0,
                    airline=item.get("airline", "")[:30],
                    flight_no=item.get("flight_no", "")[:10],
                    aircraft="",
                    departure_time=item.get("departure_time", ""),
                    arrival_time=item.get("arrival_time", ""),
                    departure_airport=query.departure,
                    arrival_airport=query.destination,
                    duration=duration,
                    stops=int(item.get("stops", 0)),
                    price=float(item.get("price", 0)),
                    cabin_class=query.cabin_class or "economy",
                    source=self.name,
                    recorded_at=now,
                    purchase_url=f"https://www.skyscanner.net/transport/flights/"
                                f"{query.departure}/{query.destination}/{query.departure_date}/",
                ))

            logger.info(f"SkyscannerSource: {len(results)} flights "
                        f"for {query.departure}->{query.destination}")
            return results

        except Exception as e:
            logger.warning(f"SkyscannerSource: search failed: {e}")
            return []
