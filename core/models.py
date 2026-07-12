"""
Flight Monitor - Data Models
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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


@dataclass
class PriceAlert:
    """Represents a price alert configuration."""
    id: Optional[int] = None
    query_id: int = 0
    target_price: float = 0.0
    is_active: bool = True
    notify_email: bool = True
    notify_wechat: bool = False
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
