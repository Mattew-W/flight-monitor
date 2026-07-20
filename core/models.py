"""
Flight Monitor - Data Models
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import math


@dataclass
class SearchQuery:
    """Represents a flight search query / monitoring task."""
    id: Optional[int] = None
    departure: str = ""          # e.g. "北京"
    destination: str = ""        # e.g. "上海"
    departure_date: str = ""     # YYYY-MM-DD
    cabin_class: str = "economy" # economy / business / first
    trip_type: str = "oneway"    # oneway / roundtrip
    return_date: str = ""        # for roundtrip
    is_monitoring: bool = False  # whether this query is being actively monitored
    created_at: str = ""
    label: str = ""              # user-friendly name


@dataclass
class FlightPrice:
    """Represents a single price record for a flight."""
    id: Optional[int] = None
    query_id: int = 0
    airline: str = ""
    flight_no: str = ""
    aircraft: str = ""
    departure_time: str = ""
    arrival_time: str = ""
    departure_airport: str = ""
    arrival_airport: str = ""
    duration: str = ""
    stops: int = 0
    price: float = 0.0
    cabin_class: str = "economy"
    source: str = ""             # which data source / platform
    recorded_at: str = ""        # ISO timestamp
    purchase_url: str = ""       # direct booking link
    # ── Revenue management features (v3) ──
    sub_class: str = ""          # 子舱位代码 Y/B/M/E/H/K/L...
    seat_inventory: int = 9      # 剩余座位数 (OTA 超过9张显示9)
    is_mock: bool = False        # True = 模拟数据, False = 真实抓取

    def __post_init__(self):
        # Sanitize price: reject NaN (would poison min()/sort()/alerts).
        # Negative prices are clamped to 0 rather than rejected, because some
        # scrapers occasionally emit -1 sentinels; the monitor's None-filter
        # already drops non-positive values before alert checks.
        if self.price is None:
            return
        if isinstance(self.price, float) and math.isnan(self.price):
            self.price = 0.0
        elif self.price < 0:
            self.price = 0.0


@dataclass
class PriceAlert:
    """Represents a price alert configuration."""
    id: Optional[int] = None
    query_id: int = 0
    target_price: float = 0.0
    is_active: bool = True
    notify_email: bool = True
    notify_wechat: bool = False
    notify_feishu: bool = True  # default: auto-send if FEISHU_WEBHOOK config exists
    created_at: str = ""
    last_triggered: str = ""


@dataclass
class AlertHistory:
    """Represents a triggered alert record."""
    id: Optional[int] = None
    alert_id: int = 0
    query_id: int = 0
    price: float = 0.0
    target_price: float = 0.0
    airline: str = ""
    flight_no: str = ""
    triggered_at: str = ""
    message: str = ""
