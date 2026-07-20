"""
Flight Monitor — Feature Engineering Pipeline
=============================================

Implements the full feature engineering pipeline from the PDF design guide:
  - Cyclical encoding for departure time, month, day-of-week
  - Holiday proximity (Gaussian decay)
  - Days-to-departure nonlinear transforms
  - Lagged price features (rolling mean, momentum, volatility)
  - Service/route encoding
  - Interaction features (distance × fuel proxy, inventory × days-left)

All features are RELATIVE (normalized) where possible, making them
market-agnostic and transferable from Indian priors.
"""
import logging
import math
import statistics
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# Constants
PEAK_MONTHS = {1, 2, 7, 8}       # Chinese New Year + summer
SHOULDER_MONTHS = {4, 5, 9, 10}  # spring/autropical
RED_EYE_HOURS = {0, 1, 2, 3, 4, 5, 22, 23}

# Hub cities for hub-to-hub premium detection (PDF §5)
HUB_CITIES = {"北京", "上海", "广州", "深圳", "成都", "重庆", "西安", "昆明", "杭州", "香港"}    # tier-1 hub cities

# Sub-class (cabin discount) mapping
SUBCLASS_WEIGHT = {
    "Y": 1.00, "B": 0.92, "M": 0.85, "H": 0.78, "K": 0.72,
    "L": 0.65, "V": 0.58, "T": 0.50, "E": 0.45, "N": 0.40,
    "Q": 0.35, "S": 0.30, "G": 0.28, "O": 0.25, "X": 0.22,
    "U": 0.20, "R": 0.18, "W": 0.15, "Z": 0.12, "P": 0.38,
    "A": 1.00, "C": 0.90, "D": 0.80, "J": 0.75, "F": 1.05,
}


def _parse_date(date_str: str) -> Optional[datetime]:
    """Try multiple date formats."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _encode_cyclical(value: float, max_val: float) -> Tuple[float, float]:
    """Encode a cyclical value (e.g., hour 0-23) into sin/cos components."""
    if not max_val:
        return 0.0, 0.0
    angle = 2 * math.pi * value / max_val
    return round(math.sin(angle), 4), round(math.cos(angle), 4)


def cyclical_time_encoding(time_str: str) -> Tuple[float, float]:
    """Encode departure time into sin/cos for 24-hour continuity."""
    if not time_str:
        return 0.0, 0.0
    try:
        parts = time_str.strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        total_minutes = hour * 60 + minute
        return _encode_cyclical(total_minutes, 1440)
    except (ValueError, IndexError):
        return 0.0, 0.0


def cyclical_month_encoding(month: int) -> Tuple[float, float]:
    """Encode month (1-12) into sin/cos for seasonal continuity."""
    return _encode_cyclical(month - 1, 12)


def cyclical_dow_encoding(dow: int) -> Tuple[float, float]:
    """Encode day-of-week (0=Mon, 6=Sun) into sin/cos."""
    return _encode_cyclical(dow, 7)


def holiday_proximity_score(
    date: datetime,
    holidays: List[Tuple[datetime, datetime]],
    sigma: float = 7.0,
) -> float:
    """Compute holiday proximity as a Gaussian-decay continuous value.

    Inside the holiday window returns 1.0. Outside decays exponentially
    with distance, controlled by sigma (days to decay to ~0.37).
    """
    for start, end in holidays:
        if start <= date <= end:
            return 1.0
        if date < start:
            distance = (start - date).days
            return round(math.exp(-(distance ** 2) / (2 * sigma ** 2)), 4)
    # Find nearest future holiday
    best_distance = 365
    for start, end in holidays:
        if start > date:
            best_distance = min(best_distance, (start - date).days)
    return round(math.exp(-(best_distance ** 2) / (2 * sigma ** 2)), 4)


def days_left_features(days_until_departure: int) -> Dict[str, float]:
    """Transform raw days-until-departure into multiple engineered features.

    These capture the nonlinear U-shaped price curve described in the PDF.
    """
    if days_until_departure <= 0:
        return {
            "days_left_raw": 0,
            "days_left_log": 0,
            "days_left_ratio": 0,
            "is_last_minute": 1,
            "is_early_bird": 0,
        }

    log_days_left = math.log1p(days_until_departure)
    # Normalize: 1.0 at ~60 days out, decreases toward 0 at departure
    days_left_ratio = min(days_until_departure / 60.0, 1.0)
    # Binary flags
    is_last_minute = 1 if days_until_departure <= 3 else 0
    is_early_bird = 1 if days_until_departure >= 45 else 0

    return {
        "days_left_raw": days_until_departure,
        "days_left_log": log_days_left,
        "days_left_ratio": days_left_ratio,
        "is_last_minute": is_last_minute,
        "is_early_bird": is_early_bird,
    }


def compute_rolling_stats(prices: List[float]) -> Dict[str, float]:
    """Compute lagged statistical features from a price series.

    Features:
      - rolling_mean_7d / rolling_mean_3d
      - rolling_std_7d / rolling_std_3d
      - momentum_3d (relative price change over last 3 days)
      - momentum_7d
      - volatility_7d (coefficient of variation)
      - price_change_1d (1日价格变化率)
      - price_change_3d (3日价格变化率)
    """
    if not prices:
        return {
            "rolling_mean_7d": 0,
            "rolling_std_7d": 0,
            "momentum_3d": 0,
            "momentum_7d": 0,
            "volatility_7d": 0,
            "price_change_1d": 0,
            "price_change_3d": 0,
            "rolling_mean_3d": 0,
            "rolling_std_3d": 0,
        }

    current = prices[-1]

    # 7-day rolling stats
    window_7 = prices[-7:] if len(prices) >= 7 else prices
    rolling_mean_7 = statistics.mean(window_7)
    rolling_std_7 = statistics.stdev(window_7) if len(window_7) > 1 else 0

    # 3-day rolling stats
    window_3 = prices[-3:] if len(prices) >= 3 else prices
    rolling_mean_3 = statistics.mean(window_3)
    rolling_std_3 = statistics.stdev(window_3) if len(window_3) > 1 else 0

    # Momentum: relative change from past to now
    momentum_3d = 0.0
    if len(prices) >= 3 and prices[-3] > 0:
        momentum_3d = (current - prices[-3]) / prices[-3]

    momentum_7d = 0.0
    if len(prices) >= 7 and prices[-7] > 0:
        momentum_7d = (current - prices[-7]) / prices[-7]

    # Price change rates
    price_change_1d = 0.0
    if len(prices) >= 2 and prices[-2] > 0:
        price_change_1d = (current - prices[-2]) / prices[-2]

    price_change_3d = 0.0
    if len(prices) >= 3 and prices[-3] > 0:
        price_change_3d = (current - prices[-3]) / prices[-3]

    # Volatility as coefficient of variation
    volatility_7d = 0.0
    if rolling_mean_7 > 0:
        volatility_7d = rolling_std_7 / rolling_mean_7

    return {
        "rolling_mean_7d": rolling_mean_7,
        "rolling_std_7d": rolling_std_7,
        "momentum_3d": momentum_3d,
        "momentum_7d": momentum_7d,
        "volatility_7d": volatility_7d,
        "price_change_1d": price_change_1d,
        "price_change_3d": price_change_3d,
        "rolling_mean_3d": rolling_mean_3,
        "rolling_std_3d": rolling_std_3,
    }


def extract_features(
    records: List[Dict],
    days_until_departure: int,
    departure_city: str,
    destination_city: str,
    cabin_class: str = "economy",
    departure_date: str = "",
    holidays: List[Tuple[datetime, datetime]] = None,
    airline_prior: Dict = None,
    time_index: float = 0.0,
) -> Dict[str, float]:
    """Extract a complete feature vector for price prediction.

    Combines all engineered features into a flat dict, ready for model input.

    Args:
        records: Historical price records (dicts with 'price', 'departure_time',
                 'sub_class', 'seat_inventory', 'stops', etc.)
        days_until_departure: Days from today to flight departure
        departure_city: Departure city name
        destination_city: Destination city name
        cabin_class: Cabin class (economy/business/first)
        departure_date: Departure date string (YYYY-MM-DD)
        holidays: List of (start, end) holiday date ranges
        airline_prior: Optional prior from Indian data extraction

    Returns:
        Flat dict with ~25 engineered features.
    """
    if not records or not any(r.get("price", 0) > 0 for r in records):
        return _empty_feature_vector()

    # Normalize optional list params early (before any iteration).
    holidays = holidays or []

    from .distance import get_distance_with_fallback

    # Parse dates
    dep_date = _parse_date(departure_date) if departure_date else datetime.now() + timedelta(days=days_until_departure)
    if dep_date is None:
        dep_date = datetime.now() + timedelta(days=days_until_departure)

    # Build pure price series
    prices = [float(r.get("price", 0)) for r in records if r.get("price", 0) > 0]
    if not prices:
        prices = [500.0]

    current_price = prices[-1]
    latest = records[-1] if records else {}

    features = {}

    # ── 1. Core price features ──
    features["current_price"] = current_price
    features["log_price"] = math.log1p(current_price)

    # ── 2. Time-to-departure features ──
    days_feats = days_left_features(days_until_departure)
    features.update(days_feats)

    # ── 3. Rolling statistics ──
    rolling = compute_rolling_stats(prices)
    features.update(rolling)

    # ── 3b. New engineered features ──
    # 距起飞天数的平方（捕捉非线性效应）
    features["days_until_departure_sq"] = float(days_until_departure ** 2)

    # 是否周末（周五/周六）
    features["is_weekend"] = 1.0 if dep_date.weekday() in (4, 5) else 0.0

    # 是否节假日期间（严格在节假日范围内）
    features["is_holiday_period"] = 0.0
    for h_start, h_end in holidays:
        if h_start <= dep_date <= h_end:
            features["is_holiday_period"] = 1.0
            break

    # 价格动量（当前价 / 7日均价 - 1）
    if rolling.get("rolling_mean_7d", 0) > 0:
        features["price_momentum"] = current_price / rolling["rolling_mean_7d"] - 1.0
    else:
        features["price_momentum"] = 0.0

    # ── 4. Cyclical time encodings ──
    dep_time_str = latest.get("departure_time", "") or ""
    time_sin, time_cos = cyclical_time_encoding(dep_time_str)
    features["dep_time_sin"] = time_sin
    features["dep_time_cos"] = time_cos

    # Departure month (cyclical)
    month_sin, month_cos = cyclical_month_encoding(dep_date.month)
    features["month_sin"] = month_sin
    features["month_cos"] = month_cos

    # Day of week (cyclical)
    dow_sin, dow_cos = cyclical_dow_encoding(dep_date.weekday())
    features["dow_sin"] = dow_sin
    features["dow_cos"] = dow_cos

    # ── 5. Holiday proximity ──
    features["holiday_proximity"] = holiday_proximity_score(dep_date, holidays)
    features["is_peak_season"] = 1.0 if dep_date.month in PEAK_MONTHS else (0.5 if dep_date.month in SHOULDER_MONTHS else 0.0)

    # ── 6. Service/route features ──
    features["stop_count"] = _parse_stops(latest.get("stops", 0))
    features["sub_class_weight"] = _encode_subclass(latest.get("sub_class", ""))
    features["inventory_pressure"] = 1.0 if int(latest.get("seat_inventory", 9) or 9) <= 3 else 0.0

    # ── 7. Cabin multiplier ──
    cabin_mult = {"economy": 1.0, "business": 2.5, "first": 4.0}.get(cabin_class, 1.0)
    features["cabin_multiplier"] = cabin_mult

    # ── 8. Data density ──
    features["data_density"] = min(len(prices) / 60.0, 1.0)
    features["has_synthetic"] = 1.0 if latest.get("is_mock", False) else 0.0

    # ── 9. Distance & interaction features ──
    duration_str = latest.get("duration", "") or ""
    duration_mins = _parse_duration_minutes(duration_str)
    distance_km = get_distance_with_fallback(departure_city, destination_city, duration_mins)
    features["distance_km"] = distance_km

    # Fuel × days interaction (PDF §3.2): uses distance as proxy when real fuel data unavailable.
    # When fuel_data module is wired in, this is replaced by real fuel rolling interaction.
    # Fuel × distance legacy interaction (kept as deprecated proxy;
    # real fuel features are fuel_interaction_30d/90d below)
    features["fuel_days_interaction"] = distance_km * duration_mins / (60.0 * 1000.0)
    features["scarcity_x_time"] = features["inventory_pressure"] * (1 - days_feats["days_left_ratio"])

    # ── 10. Indian prior integration (if available) ──
    if airline_prior:
        data_weight = min(len(prices) / 60.0, 1.0)
        prior_weight = 1.0 - data_weight
        features["prior_volatility"] = airline_prior.get("lcc_fsc_behavior", {}).get("tier_stats", {}).get("lcc", {}).get("volatility", 0.05)
        features["prior_weight"] = prior_weight
    else:
        features["prior_volatility"] = 0.0
        features["prior_weight"] = 0.0

    # ── 11. Time slot binning (PDF §4.1) ──
    # Map departure hour to 4 business-relevant time periods.
    # This explicit binning improves interpretability vs pure sin/cos.
    dep_hour_val = _parse_hour(latest.get("departure_time", ""))
    features["time_slot"] = _encode_time_slot(dep_hour_val)

    # ── 12. Regime indicator (PDF §5) ──
    # Detect macro-economic regime: normal=0, crisis=1, post_crisis=2.
    # Prevents model from "cognitive confusion" when market structure shifts.
    features["regime"] = _encode_regime(dep_date)

    # ── 13. Hub premium (PDF §5) ──
    # Hub-to-hub routes have higher base fares due to market power.
    features["hub_premium"] = 1.0 if (departure_city in HUB_CITIES and destination_city in HUB_CITIES) else 0.0

    # ── 14. Time index (for trend learning) ──
    # Allows model to learn long-term trends in the data
    features["time_index"] = time_index

    # ── 15. Real fuel price interaction (PDF §3.2) ──
    # City + duration based: fuel price varies by region and flight length
    try:
        from .fuel_data import FuelPriceProvider
        _fuel_provider = FuelPriceProvider()
        fuel_30d = _fuel_provider.get_fuel_interaction(
            departure_city, destination_city, duration_mins, dep_date, 30
        )
        fuel_90d = _fuel_provider.get_fuel_interaction(
            departure_city, destination_city, duration_mins, dep_date, 90
        )
    except Exception:
        fuel_30d = distance_km * days_until_departure / 1000.0
        fuel_90d = fuel_30d
    features["fuel_interaction_30d"] = fuel_30d
    features["fuel_interaction_90d"] = fuel_90d

    return features


def _empty_feature_vector() -> Dict[str, float]:
    """Return a zero-filled feature vector when no data is available."""
    n = len(_get_feature_names())
    return {name: 0.0 for name in _get_feature_names()}


def _get_feature_names() -> List[str]:
    """Return the canonical feature name list for model input ordering."""
    return [
        "current_price",
        "log_price",
        "days_left_raw",
        "days_left_log",
        "days_left_ratio",
        "is_last_minute",
        "is_early_bird",
        "rolling_mean_7d",
        "rolling_std_7d",
        "momentum_3d",
        "momentum_7d",
        "volatility_7d",
        "price_change_1d",
        "price_change_3d",
        "rolling_mean_3d",
        "rolling_std_3d",
        "days_until_departure_sq",
        "is_weekend",
        "is_holiday_period",
        "price_momentum",
        "dep_time_sin",
        "dep_time_cos",
        "month_sin",
        "month_cos",
        "dow_sin",
        "dow_cos",
        "holiday_proximity",
        "is_peak_season",
        "stop_count",
        "sub_class_weight",
        "inventory_pressure",
        "cabin_multiplier",
        "data_density",
        "has_synthetic",
        "distance_km",
        "fuel_days_interaction",
        "scarcity_x_time",
        "prior_volatility",
        "prior_weight",
        "time_slot",
        "regime",
        "hub_premium",
        "time_index",
        "fuel_interaction_30d",
        "fuel_interaction_90d",
    ]


def _parse_hour(time_str: str) -> int:
    """Parse hour from time string like '22:20' or '14:30'. Returns -1 on error."""
    if not time_str:
        return -1
    parts = time_str.strip().split(":")
    try:
        return int(parts[0])
    except (ValueError, IndexError):
        return -1


def _encode_time_slot(hour: int) -> float:
    """Map departure hour to 4 time periods.
    
    Per PDF §4.1: explicit binning improves interpretability.
      0 = morning   (6-11):  golden business hours, premium pricing
      1 = afternoon (12-17): moderate pricing
      2 = evening   (18-21): moderate-high pricing
      3 = redeye    (22-5):  deep discount
      -1 = unknown
    """
    if hour < 0:
        return -1.0
    if 6 <= hour < 12:
        return 0.0  # morning
    elif 12 <= hour < 18:
        return 1.0  # afternoon
    elif 18 <= hour < 22:
        return 2.0  # evening
    else:
        return 3.0  # redeye


def _encode_regime(date: datetime) -> float:
    """Encode macro-economic regime per PDF §5.
    
    0 = normal   (post-2022)
    1 = crisis   (2020, COVID)
    2 = recovery (2021-2022)

    Prevents models trained across structural breaks from "cognitive confusion".
    Future enhancement: connect to external event database.
    """
    if date is None:
        return 0.0
    year = date.year
    if year <= 2020:
        return 1.0  # crisis (COVID)
    elif year <= 2022:
        return 2.0  # recovery
    else:
        return 0.0  # normal


def _parse_stops(stops_val) -> int:
    """Parse various stop count formats to integer."""
    if stops_val is None:
        return 0
    if isinstance(stops_val, int):
        return stops_val
    s = str(stops_val).lower()
    if "non-stop" in s or s in ("0", "none"):
        return 0
    import re
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else 0


def _parse_duration_minutes(dur_str: str) -> int:
    """Parse duration string like '2h 50m' to minutes. Returns 0 on error."""
    if not dur_str:
        return 0
    import re
    m = re.match(r"^(\d+)h\s*(\d+)m", dur_str.strip())
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r"^(\d+)h$", dur_str.strip())
    if m:
        return int(m.group(1)) * 60
    return 0


def _encode_subclass(sc: str) -> float:
    """Map fare class code to discount weight."""
    if not sc:
        return 0.7
    sc = sc.strip().upper()
    if sc in SUBCLASS_WEIGHT:
        return SUBCLASS_WEIGHT[sc]
    return 0.7
