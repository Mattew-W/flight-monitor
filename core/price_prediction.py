"""
Flight Monitor - Price Prediction Engine v2
Route-aware prediction with 6 distinct pricing patterns based on real-world airline behavior.
Each route type generates uniquely shaped historical curves and forecasts.
"""
import hashlib
import logging
import math
import random
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)


def _stable_seed(*parts) -> int:
    """Produce a stable integer seed from arbitrary string parts.

    Uses md5 (NOT Python's built-in hash()) so the same input always yields the
    same seed across processes — Python's hash() is randomized via PYTHONHASHSEED
    for str, which would make synthetic history fluctuate between restarts.
    """
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.md5(raw.encode("utf-8")).hexdigest()[:8], 16)


# =====================================================================
#  ROUTE CLASSIFICATION ENGINE
# =====================================================================

# Competitive routes: many airlines, frequent flights, price wars
COMPETITIVE_ROUTES = {
    ("北京", "上海"), ("上海", "北京"), ("北京", "广州"), ("广州", "北京"),
    ("北京", "深圳"), ("深圳", "北京"), ("上海", "深圳"), ("深圳", "上海"),
    ("上海", "广州"), ("广州", "上海"), ("成都", "重庆"), ("重庆", "成都"),
    ("广州", "深圳"), ("深圳", "广州"),
}

# Monopoly / remote routes: few airlines, limited flights
MONOPOLY_ROUTES = {
    ("成都", "拉萨"), ("拉萨", "成都"), ("北京", "拉萨"), ("拉萨", "北京"),
    ("北京", "九寨沟"), ("九寨沟", "北京"), ("成都", "九寨沟"), ("九寨沟", "成都"),
    ("成都", "敦煌"), ("敦煌", "成都"), ("北京", "阿勒泰"), ("阿勒泰", "北京"),
    ("乌鲁木齐", "喀什"), ("喀什", "乌鲁木齐"),
}

# Budget-heavy routes (Spring Airlines, Juneyao dominant)
BUDGET_ROUTES = {
    ("上海", "石家庄"), ("石家庄", "上海"), ("上海", "汕头"), ("汕头", "上海"),
    ("上海", "兰州"), ("兰州", "上海"), ("上海", "桂林"), ("桂林", "上海"),
    ("杭州", "三亚"), ("三亚", "杭州"), ("上海", "张家界"), ("张家界", "上海"),
    ("宁波", "大连"), ("大连", "宁波"),
}

# Chinese holiday rules (lunar-based, approximate Gregorian)
# Each entry: (month, anchor_day, name, duration_days, lead_days)
_HOLIDAY_RULES = [
    # Spring Festival: ~Jan 21 - Feb 20, 7 days
    (1, 28, "春节", 7, 10),
    # Qingming: ~Apr 4-5, 3 days
    (4, 5, "清明", 3, 2),
    # Labor Day: May 1-5, 5 days
    (5, 1, "五一", 5, 3),
    # Dragon Boat: ~late May / early June, 3 days
    (5, 31, "端午", 3, 2),
    # Summer vacation: Jul 1 - Aug 31
    (7, 1, "暑假", 62, 20),
    # Mid-Autumn: ~Sep 15-17, + National Day Oct 1-7
    (9, 15, "中秋+国庆", 24, 14),
    # New Year: Dec 31 - Jan 2
    (12, 31, "元旦", 3, 2),
]


class HolidayManager:
    """Dynamic holiday engine — no hardcoded year.

    Uses approximate Gregorian offsets for lunar festivals.
    Cache lasts 1 day before auto-refresh.
    For production, replace _HOLIDAY_RULES with an API or database-backed table.
    """
    _cache: Dict[int, List[Tuple[datetime, datetime, str]]] = {}
    _last_refresh: Optional[datetime] = None

    @classmethod
    def get_holidays(cls, year: int) -> List[Tuple[datetime, datetime, str]]:
        now = datetime.now()
        if cls._cache and cls._last_refresh and (now - cls._last_refresh).days < 1:
            if year in cls._cache:
                return cls._cache[year]
        holidays = []
        for month, anchor_day, name, duration, _ in _HOLIDAY_RULES:
            start = datetime(year, month, anchor_day)
            end = start + timedelta(days=duration)
            if month == 12:
                end = datetime(year + 1, 1, 2)
            holidays.append((start, end, name))
        cls._cache[year] = holidays
        cls._last_refresh = now
        return holidays


HOLIDAYS_2026 = HolidayManager.get_holidays(2026)  # Backward compat


def _classify_route(departure: str, destination: str, dep_date: datetime) -> Dict:
    """Classify a route into one of 6 pricing profile types.
    
    Returns a dict with:
      - profile: one of 'competitive','moderate','monopoly','budget','holiday','offpeak'
      - description: human-readable label
      - airline_count: estimated number of competing airlines
      - volatility: price volatility factor (0-1)
    """
    route_key = (departure, destination)

    # 1. Holiday check first (overrides everything) — dynamic year
    for start, end, name in HolidayManager.get_holidays(dep_date.year):
        # ±1 day buffer around holidays
        if (start - timedelta(days=1)) <= dep_date <= (end + timedelta(days=1)):
            return {
                "profile": "holiday",
                "description": f"{name}高峰",
                "airline_count": 1,
                "volatility": 0.9,
                "holiday_name": name,
            }

    # 2. Competitive routes
    if route_key in COMPETITIVE_ROUTES:
        return {
            "profile": "competitive",
            "description": "多家航司激烈竞争",
            "airline_count": 6,
            "volatility": 0.6,
        }

    # 3. Monopoly routes
    if route_key in MONOPOLY_ROUTES:
        return {
            "profile": "monopoly",
            "description": "有限航司执飞",
            "airline_count": 2,
            "volatility": 0.3,
        }

    # 4. Budget routes
    if route_key in BUDGET_ROUTES:
        return {
            "profile": "budget",
            "description": "廉航主导航线",
            "airline_count": 3,
            "volatility": 0.85,
        }

    # 5. International / long-haul (departure domestic, destination international)
    from config import CITY_CODES
    dep_code = CITY_CODES.get(departure, "")
    dst_code = CITY_CODES.get(destination, "")
    DOMESTIC_IATA = {
        "BJS","SHA","CAN","SZX","CTU","HGH","WUH","XIY","CKG","TAO",
        "CSX","NKG","XMN","KMG","DLC","TSN","CGO","SYX","HAK","HRB",
        "SHE","CGQ","KWE","NNG","LHW","URC","LXA","INC","XNN","HET",
        "SJW","TYN","HFE","KHN","TNA","FOC","WNZ","NGB","YNT","WEH",
        "ZUH","KWL","LJG","DLU","DNH","JZH","DYG","JHG","AAT","KHG",
        "YIN","KRL","BAV","DSN","LYA","NTG","WUX","CZX","XUZ","YIW",
        "SWA","ZHA","BHY","TXN",
    }
    dep_dom = dep_code in DOMESTIC_IATA
    dst_dom = dst_code in DOMESTIC_IATA or destination in ("香港","澳门","台北","高雄")
    is_intl = not (dep_dom and dst_dom)
    if is_intl:
        return {
            "profile": "offpeak",
            "description": "国际航线",
            "airline_count": 5,
            "volatility": 0.4,
        }

    # 6. Default: moderate domestic competition
    return {
        "profile": "moderate",
        "description": "温和竞争",
        "airline_count": 4,
        "volatility": 0.5,
    }


# =====================================================================
#  PER-PROFILE SYNTHETIC HISTORY GENERATORS
# =====================================================================

def _synthetic_competitive(current_price: float, days_back: int, rng: random.Random) -> List[Dict]:
    """Competitive route: prices drop ~15% over 2 weeks then spike last 3 days.
    Historical: high start -> deep dip around day 18-14 -> rise to current."""
    data = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # Start ~18% higher 30 days ago, dips to ~85% at day 14, then back up
    for i in range(days_back, 0, -1):
        d = today - timedelta(days=i)
        ratio = (days_back - i) / days_back  # 0 = 30d ago, 1 = today
        # Deep U: 118% -> 85% -> back to 100%
        if ratio < 0.5:
            # First half: linear descent from 118% to 85%
            phase = ratio / 0.5
            trend = 1.18 - phase * 0.33
        else:
            # Second half: slight recovery 85% -> 100%
            phase = (ratio - 0.5) / 0.5
            trend = 0.85 + phase * 0.15
        # Add competitive noise (price wars cause more volatility)
        noise = 1 + rng.uniform(-0.08, 0.08)
        avg = current_price * trend * noise
        avg = max(current_price * 0.55, min(current_price * 1.4, avg))
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "min_price": round(avg * rng.uniform(0.85, 0.95)),
            "avg_price": round(avg),
            "max_price": round(avg * rng.uniform(1.05, 1.18)),
        })
    return data


def _synthetic_moderate(current_price: float, days_back: int, rng: random.Random) -> List[Dict]:
    """Moderate route: gentle U-curve with small dips.
    Historical: start ~108% -> slow drift down to ~95% -> current."""
    data = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(days_back, 0, -1):
        d = today - timedelta(days=i)
        ratio = (days_back - i) / days_back
        # Subtle U: 108% -> 94% -> 100%
        t = ratio - 0.55
        trend = 0.94 + t * t * 2.5
        noise = 1 + rng.uniform(-0.05, 0.05)
        avg = current_price * trend * noise
        avg = max(current_price * 0.6, min(current_price * 1.3, avg))
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "min_price": round(avg * rng.uniform(0.88, 0.96)),
            "avg_price": round(avg),
            "max_price": round(avg * rng.uniform(1.04, 1.12)),
        })
    return data


def _synthetic_monopoly(current_price: float, days_back: int, rng: random.Random) -> List[Dict]:
    """Monopoly route: consistently expensive, prices drift steadily upward.
    Historical: 30d ago was cheaper (~92%), steady climb to current."""
    data = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(days_back, 0, -1):
        d = today - timedelta(days=i)
        ratio = (days_back - i) / days_back
        # Near-linear rise: 92% -> 100%, low volatility
        trend = 0.92 + ratio * 0.08
        noise = 1 + rng.uniform(-0.03, 0.03)
        avg = current_price * trend * noise
        avg = max(current_price * 0.7, min(current_price * 1.2, avg))
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "min_price": round(avg * rng.uniform(0.92, 0.97)),
            "avg_price": round(avg),
            "max_price": round(avg * rng.uniform(1.03, 1.08)),
        })
    return data


def _synthetic_budget(current_price: float, days_back: int, rng: random.Random) -> List[Dict]:
    """Budget airline route: zigzag with 2-3 flash sales (price drops).
    Historical: multiple sawtooth patterns, high volatility."""
    data = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # Flash sale days (sudden 20-30% drops)
    flash_sale_days = {5, 12, 22}
    for i in range(days_back, 0, -1):
        d = today - timedelta(days=i)
        ratio = (days_back - i) / days_back
        trend = 1.0  # base
        # Zigzag around trend with occasional flash sales
        zig = math.sin(ratio * math.pi * 4) * 0.06  # ~6% oscillation
        trend = 1.0 + zig
        # Flash sale on specific days
        if i in flash_sale_days:
            trend -= rng.uniform(0.15, 0.28)
        noise = 1 + rng.uniform(-0.10, 0.10)
        avg = current_price * trend * noise
        avg = max(current_price * 0.40, min(current_price * 1.5, avg))
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "min_price": round(avg * rng.uniform(0.78, 0.90)),
            "avg_price": round(avg),
            "max_price": round(avg * rng.uniform(1.05, 1.20)),
        })
    return data


def _synthetic_holiday(current_price: float, days_back: int, rng: random.Random) -> List[Dict]:
    """Holiday route: steep climb as holiday approaches.
    Historical: 30d ago was MUCH cheaper (~70%), exponential rise."""
    data = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(days_back, 0, -1):
        d = today - timedelta(days=i)
        ratio = (days_back - i) / days_back
        # Exponential rise: 70% -> 85% -> 100%
        # Accelerates in the last 10 days
        if ratio < 0.66:
            trend = 0.70 + ratio * 0.12 / 0.66
        else:
            inner = (ratio - 0.66) / 0.34
            trend = 0.82 + inner * inner * 0.18
        noise = 1 + rng.uniform(-0.06, 0.06)
        avg = current_price * trend * noise
        avg = max(current_price * 0.4, min(current_price * 1.6, avg))
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "min_price": round(avg * rng.uniform(0.88, 0.96)),
            "avg_price": round(avg),
            "max_price": round(avg * rng.uniform(1.06, 1.22)),
        })
    return data


def _synthetic_offpeak(current_price: float, days_back: int, rng: random.Random) -> List[Dict]:
    """Off-peak international: inverted-U (prices peak in the middle of the window).
    Historical: starts low (~90%), peaks around day 15 (~110%), drops back."""
    data = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(days_back, 0, -1):
        d = today - timedelta(days=i)
        ratio = (days_back - i) / days_back
        # Inverted U: 90% -> 110% at ratio=0.5 -> 100%
        t = ratio - 0.5
        trend = 1.0 - t * t * 0.8 + 0.05  # peak at 1.05, edges at 0.85-0.90
        noise = 1 + rng.uniform(-0.05, 0.05)
        avg = current_price * trend * noise
        avg = max(current_price * 0.5, min(current_price * 1.4, avg))
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "min_price": round(avg * rng.uniform(0.86, 0.94)),
            "avg_price": round(avg),
            "max_price": round(avg * rng.uniform(1.04, 1.15)),
        })
    return data


_SYNTHETIC_GENERATORS = {
    "competitive": _synthetic_competitive,
    "moderate": _synthetic_moderate,
    "monopoly": _synthetic_monopoly,
    "budget": _synthetic_budget,
    "holiday": _synthetic_holiday,
    "offpeak": _synthetic_offpeak,
}


def generate_synthetic_historical_data(
    current_price: float,
    profile: str = "moderate",
    days_back: int = 30,
) -> List[Dict]:
    """Generate route-profile-aware synthetic historical price data."""
    if current_price <= 0:
        return []
    rng = random.Random(int(current_price * 1000 + _stable_seed(profile)) % 2**31)
    gen = _SYNTHETIC_GENERATORS.get(profile, _synthetic_moderate)
    return gen(current_price, days_back, rng)


# =====================================================================
#  DATA-DRIVEN FORECAST MODELS (replaces hardcoded formulas)
# =====================================================================

def _linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """Simple linear regression: returns (slope, intercept)."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)
    denom = n * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-10:
        return 0.0, sum_y / n
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def _compute_residual_std(prices: List[float], slope: float, intercept: float) -> float:
    """Compute residual standard deviation for confidence intervals."""
    n = len(prices)
    if n < 3:
        return max(abs(slope) * 2, 50)
    residuals = [prices[i] - (intercept + slope * i) for i in range(n)]
    mean_sq = sum(r * r for r in residuals) / (n - 2)
    return math.sqrt(max(mean_sq, 1.0))


def _wma_forecast(prices: List[float], days_ahead: int) -> Tuple[List[float], float]:
    """Weighted Moving Average: more weight to recent prices.
    Returns (forecast_list, trend_strength)."""
    n = len(prices)
    if n < 2:
        return [prices[-1]] * days_ahead if prices else [0] * days_ahead, 0.0

    weights = list(range(1, n + 1))
    w_sum = sum(weights)
    wma = sum(p * w for p, w in zip(prices, weights)) / w_sum

    # Trend from last few points
    recent_n = min(5, n)
    recent = prices[-recent_n:]
    diffs = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
    avg_diff = sum(diffs) / len(diffs) if diffs else 0.0

    forecast = []
    val = prices[-1]
    for d in range(1, days_ahead + 1):
        decay = 1.0 / (1.0 + 0.1 * d)
        val = wma * (1 - decay) + (val + avg_diff) * decay
        forecast.append(round(val))

    # Trend strength: how much of the series variance is explained by trend
    if n >= 3:
        total_var = sum((p - wma) ** 2 for p in prices) / n
        trend_strength = min(1.0, abs(avg_diff) * n / (total_var + 1))
    else:
        trend_strength = 0.3

    return forecast, trend_strength


def _ci_bands(forecast: List[float], residual_std: float,
              current: float, days_ahead: int) -> Tuple[List[float], List[float]]:
    """Generate 95% confidence interval bands around forecast."""
    lower, upper = [], []
    for i, f in enumerate(forecast):
        t_factor = 1.96 * math.sqrt((i + 1) / max(days_ahead, 1))
        margin = residual_std * t_factor
        lower.append(round(max(current * 0.4, f - margin)))
        upper.append(round(min(current * 1.8, f + margin)))
    return lower, upper


def data_driven_forecast(
    prices: List[float],
    days_ahead: int,
    profile: str = "moderate",
) -> Dict:
    """Pure data-driven forecast using linear regression + WMA blend.

    Uses actual price history, not hardcoded formulas.
    Fallback to route-aware synthetic only if < 3 data points.
    """
    valid_prices = [p for p in prices if p > 0]
    if len(valid_prices) < 3:
        return _minimal_forecast(prices, days_ahead, profile)

    current = valid_prices[-1]
    n = len(valid_prices)

    # 1. Linear regression on full series
    xs = list(range(n))
    slope, intercept = _linear_regression(xs, valid_prices)
    residual_std = _compute_residual_std(valid_prices, slope, intercept)

    # 2. WMA forecast with trend
    wma_forecast, trend_strength = _wma_forecast(valid_prices, days_ahead)

    # 3. Linear extrapolation
    lin_forecast = [round(intercept + slope * (n + d)) for d in range(1, days_ahead + 1)]

    # 4. Blend: WMA_weight depends on trend_strength
    #    Strong trend → more linear, weak trend → more WMA
    wma_weight = 0.7 - 0.3 * trend_strength     # 0.4 ~ 0.7
    lin_weight = 1.0 - wma_weight

    forecast = [
        round(wma_forecast[i] * wma_weight + lin_forecast[i] * lin_weight)
        for i in range(days_ahead)
    ]

    # 5. Confidence intervals
    lower, upper = _ci_bands(forecast, residual_std, current, days_ahead)

    return {
        "forecast": forecast,
        "lower": lower,
        "upper": upper,
        "model": f"Data-Driven LR+WMA ({n} points)",
        "profile": profile,
        "profile_label": _PROFILE_LABELS.get(profile, profile),
    }


def _minimal_forecast(prices: List[float], days_ahead: int,
                      profile: str) -> Dict:
    """Fallback when < 3 data points: use synthetic history with route context."""
    valid = [p for p in prices if p > 0]
    current = valid[-1] if valid else 500
    profile_vol = {
        "competitive": 0.06, "moderate": 0.04, "monopoly": 0.02,
        "budget": 0.08, "holiday": 0.10, "offpeak": 0.03,
    }.get(profile, 0.04)

    rng = random.Random(int(current * 1000 + _stable_seed(profile)) % 2**31)
    forecast, lower, upper = [], [], []
    price = current
    for d in range(1, days_ahead + 1):
        drift = rng.uniform(-profile_vol, profile_vol)
        decay = 1.0 / (1.0 + 0.05 * d)
        price = price * decay + current * (1 - decay) + drift * current
        forecast.append(round(price))
        ci = current * (0.08 + 0.12 * d / max(days_ahead, 1))
        lower.append(round(max(current * 0.5, price - ci)))
        upper.append(round(min(current * 1.5, price + ci)))

    return {
        "forecast": forecast,
        "lower": lower,
        "upper": upper,
        "model": f"Statistical Estimate (数据不足, {len(valid)} 点)",
        "profile": profile,
        "profile_label": _PROFILE_LABELS.get(profile, profile),
    }


# Profile label mapping for UI
_PROFILE_LABELS = {
    "competitive": "竞争激烈 — 降价窗口",
    "moderate": "温和竞争 — 波动不大",
    "monopoly": "有限执飞 — 持续上涨",
    "budget": "廉航主导 — 关注促销",
    "holiday": "节假日高峰 — 尽早购买",
    "offpeak": "淡季长线 — 不急出手",
}


# =====================================================================
#  FORECAST ENGINE (data-driven)
# =====================================================================

def route_aware_forecast(
    prices: List[float],
    days_ahead: int,
    profile: str = "moderate",
) -> Dict:
    """Generate data-driven price forecast with route context.

    Uses actual price history via linear regression + WMA,
    not hardcoded formulas.
    """
    current = prices[-1] if prices else 0
    if current <= 0:
        return {
            "forecast": [0] * days_ahead,
            "lower": [0] * days_ahead,
            "upper": [0] * days_ahead,
            "model": "No Data",
            "profile": profile,
            "profile_label": _PROFILE_LABELS.get(profile, profile),
        }
    return data_driven_forecast(prices, days_ahead, profile)


def arima_forecast(
    prices: List[float],
    days_ahead: int,
    order: Tuple[int, int, int] = (1, 1, 1),
    n_simulations: int = 100,
) -> Dict:
    """Data-driven forecast using linear regression + WMA blend.

    Uses real price history, not hardcoded ARIMA assumptions.
    Falls back safely when data is sparse.
    """
    return data_driven_forecast(prices, days_ahead, "moderate")


def _linear_forecast(prices: List[float], days_ahead: int) -> Dict:
    """Fallback: pure linear regression forecast."""
    valid = [p for p in prices if p > 0]
    if len(valid) < 2:
        price = valid[-1] if valid else 0
        return {
            "forecast": [round(price)] * days_ahead,
            "lower": [round(price * 0.85)] * days_ahead,
            "upper": [round(price * 1.15)] * days_ahead,
            "model": "Flat (insufficient data)",
        }
    n = len(valid)
    xs = list(range(n))
    slope, intercept = _linear_regression(xs, valid)
    residual_std = _compute_residual_std(valid, slope, intercept)
    current = valid[-1]
    forecasts, lower_bounds, upper_bounds = [], [], []
    for d in range(1, days_ahead + 1):
        fp = max(0, intercept + slope * (n - 1 + d))
        margin = residual_std * 1.96 * math.sqrt(d)
        forecasts.append(round(fp))
        lower_bounds.append(round(max(current * 0.3, fp - margin)))
        upper_bounds.append(round(min(current * 2.5, fp + margin)))
    return {
        "forecast": forecasts,
        "lower": lower_bounds,
        "upper": upper_bounds,
        "model": "Linear Regression",
    }


# Legacy wrapper for backward compatibility
def rule_based_forecast(prices: List[float], days_ahead: int) -> Dict:
    """Legacy wrapper: delegates to route_aware_forecast with moderate profile."""
    return route_aware_forecast(prices, days_ahead, "moderate")


# =====================================================================
#  MAIN CHART GENERATION
# =====================================================================

def get_historical_prices(db, query_id: int, days_back: int = 30,
                          real_only: bool = True,
                          include_mock: bool = False) -> List[Dict]:
    """Get rich historical price records for ML modeling or chart display.

    Uses direct SQL subquery to locate the *exact* lowest-price record
    per day — preserving flight-level metadata (departure_time, sub_class,
    seat_inventory, stops) that aggregated GROUP BY would destroy.

    Args:
        real_only: additionally restrict to source='ctrip_browser'.
        include_mock: include mock data (is_mock=1). Used for chart display
            to give a richer history; ML training must keep this False.

    Returns one rich dict per date with: date, price, min_price, avg_price,
    departure_time, sub_class, seat_inventory, stops.
    """
    try:
        conn = db._get_conn()
        source_cond = "AND source = 'ctrip_browser'" if real_only else ""
        mock_cond = "" if include_mock else "AND is_mock = 0"
        sql = f"""
            SELECT pr.*, DATE(pr.recorded_at) as date
            FROM price_records pr
            INNER JOIN (
                SELECT DATE(recorded_at) as date, MIN(price) as min_price
                FROM price_records
                WHERE query_id = ? {mock_cond} {source_cond}
                GROUP BY DATE(recorded_at)
            ) grouped
            ON DATE(pr.recorded_at) = grouped.date
               AND pr.price = grouped.min_price
            WHERE pr.query_id = ? {mock_cond} {source_cond}
            ORDER BY date ASC
        """
        rows = conn.execute(sql, (query_id, query_id)).fetchall()

        if not rows:
            return []

        # Deduplicate: keep one richest record per date
        by_date = {}
        for r in rows:
            d = r["date"]
            if d not in by_date:
                by_date[d] = {
                    "date": d,
                    "price": float(r["price"]),
                    "min_price": float(r["price"]),
                    "avg_price": float(r["price"]),
                    "departure_time": (r["departure_time"] or ""),
                    "sub_class": (r["sub_class"] if "sub_class" in r.keys() else ""),
                    "seat_inventory": int(r["seat_inventory"]) if "seat_inventory" in r.keys() else 9,
                    "stops": int(r["stops"]) if "stops" in r.keys() else 0,
                }
        return sorted(by_date.values(), key=lambda x: x["date"])
    except Exception as e:
        logger.error(f"Error getting historical prices: {e}")
        return []


def generate_prediction_chart(
    db,
    query_id: int,
    departure: str,
    destination: str,
    departure_date: str,
    cabin_class: str = "economy",
) -> Dict:
    """Generate a fully route-aware price prediction chart.
    
    Returns chart-ready JSON with historical data, forecast, confidence intervals,
    route profile information, and a buy/wait recommendation.
    """
    # Parse departure date
    try:
        dep_date = datetime.strptime(departure_date, "%Y-%m-%d")
    except ValueError:
        try:
            dep_date = datetime.strptime(departure_date, "%Y-%m-%dT%H:%M:%S")
            departure_date = dep_date.strftime("%Y-%m-%d")
        except ValueError:
            logger.error(f"Invalid departure date: {departure_date}")
            return {"error": "Invalid departure date"}

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_until_departure = max(1, (dep_date - today).days)

    if dep_date < today:
        return {
            "error": "出发日期已过，无法生成预测",
            "departure_date": departure_date,
            "days_until_departure": 0,
        }

    # Classify the route
    route_info = _classify_route(departure, destination, dep_date)
    profile = route_info["profile"]

    # Get historical data — all sources for prediction depth
    historical = get_historical_prices(db, query_id, days_back=30,
                                       real_only=False, include_mock=True)
    # Real-only count for confidence display
    real_hist = get_historical_prices(db, query_id, days_back=30,
                                     real_only=False, include_mock=False)
    valid_hist = [h for h in historical if h.get("avg_price", 0) > 0 or h.get("min_price", 0) > 0]

    if not valid_hist:
        return {
            "error": "无有效价格数据，请先进行一次搜索",
            "departure_date": departure_date,
            "days_until_departure": days_until_departure,
        }

    # Use latest price as anchor
    current_price = valid_hist[-1].get("avg_price", 0) or valid_hist[-1].get("min_price", 0)

    # Supplement with synthetic data if too few distinct dates
    # CRITICAL: synthetic data is for chart DISPLAY only — NEVER used for ML training
    real_data_points = len(valid_hist)
    is_synthetic = False
    if real_data_points < 3:
        synthetic = generate_synthetic_historical_data(current_price, profile, 30)
        if synthetic:
            real_dates = {h["date"] for h in valid_hist}
            synthetic = [s for s in synthetic if s["date"] not in real_dates]
            historical = synthetic + valid_hist
            historical.sort(key=lambda x: x["date"])
            is_synthetic = True
        else:
            rng = random.Random(int(current_price * 1000 + _stable_seed(profile)) % 2**31)
            gen = _SYNTHETIC_GENERATORS.get(profile, _synthetic_moderate)
            synthetic = gen(current_price, 30, rng)
            real_dates = {h["date"] for h in valid_hist}
            synthetic = [s for s in synthetic if s["date"] not in real_dates]
            historical = synthetic + valid_hist
            historical.sort(key=lambda x: x["date"])
            is_synthetic = True
    else:
        historical = valid_hist

    # Extract price series (chart display — may include synthetic)
    hist_dates = [h["date"] for h in historical]
    hist_prices = [h.get("avg_price", 0) or h.get("min_price", 0) for h in historical]
    valid_prices = [p for p in hist_prices if p > 0]

    # ML training — pass rich dicts directly (departure_time/sub_class/inventory
    # are already embedded in each record via get_historical_prices).
    ml_records = get_historical_prices(db, query_id, days_back=30,
                                       real_only=False, include_mock=False)

    if not valid_prices:
        return {
            "error": "无有效价格数据",
            "departure_date": departure_date,
            "days_until_departure": days_until_departure,
        }

    # Generate forecast — try Ensemble ML first, fall back to stats
    # ML trains ONLY on real data (is_mock=0), never synthetic
    if len(ml_records) >= 7:
        try:
            from .ml_predictor import predict_with_ensemble
            ml_result = predict_with_ensemble(
                ml_records, departure, destination,
                days_until_departure, profile, cabin_class, departure_date,
                n_estimators=50,
            )
            if "error" not in ml_result:
                prediction_result = {
                    "forecast": ml_result["forecast"],
                    "lower": ml_result["lower"],
                    "upper": ml_result["upper"],
                    "model": f"Ensemble {ml_result.get('engine', 'ML')} (GBR+RFR+Ridge)",
                    "profile": profile,
                    "profile_label": _PROFILE_LABELS.get(profile, profile),
                    "evaluation": ml_result.get("evaluation", {}),
                    "feature_importance": ml_result.get("feature_importance", {}),
                }
            else:
                raise ValueError(ml_result["error"])
        except Exception as e:
            logger.debug(f"Ensemble ML failed ({e}), using stats model")
            prediction_result = arima_forecast(valid_prices, days_until_departure)
            prediction_result["profile"] = profile
            prediction_result["profile_label"] = _PROFILE_LABELS.get(profile, profile)
    elif real_data_points >= 5:
        prediction_result = arima_forecast(valid_prices, days_until_departure)
        prediction_result["profile"] = profile
        prediction_result["profile_label"] = _PROFILE_LABELS.get(profile, profile)
    else:
        prediction_result = route_aware_forecast(valid_prices, days_until_departure, profile)

    # Generate future dates
    future_dates = []
    for i in range(1, days_until_departure + 1):
        future_dates.append((today + timedelta(days=i)).strftime("%Y-%m-%d"))

    # Key metrics
    predicted_min = min(prediction_result["forecast"]) if prediction_result["forecast"] else current_price
    predicted_max = max(prediction_result["forecast"]) if prediction_result["forecast"] else current_price
    predicted_min_idx = prediction_result["forecast"].index(predicted_min)
    predicted_min_date = future_dates[predicted_min_idx] if predicted_min_idx < len(future_dates) else ""
    historical_min = min(valid_prices)

    # ── Best-buy decision engine ──
    drop_pct  = (current_price - predicted_min) / current_price * 100  # expected drop %
    rise_pct  = (predicted_max - current_price) / current_price * 100  # expected rise %
    near_low  = current_price <= historical_min * 1.03               # within 3% of all-time low
    enough_time = days_until_departure >= 14
    very_soon   = days_until_departure <= 3

    best_buy_desc = ""

    if very_soon:
        # ── Urgency: departure imminent ──
        best_buy_desc = f"距起飞仅{days_until_departure}天，建议立即购买"

    elif profile == "holiday":
        # ── Holiday: always buy ASAP ──
        if enough_time:
            best_buy_desc = f"节假日前{rise_pct:.0f}%涨幅预期，建议尽快锁定价格"
        else:
            best_buy_desc = f"节假日出行，价格持续高位，请尽快购买"

    elif profile == "monopoly" and rise_pct > 2:
        # ── Monopoly + rising ──
        best_buy_desc = f"航线竞争少，价格预计上涨{rise_pct:.0f}%，建议尽早入手"

    elif drop_pct >= 10 and enough_time:
        # ── Big drop ahead, plenty of time → wait ──
        if profile == "competitive":
            best_buy_desc = f"预计降至¥{predicted_min:.0f}（降{drop_pct:.0f}%），最佳入手: {predicted_min_date}"
        elif profile == "budget":
            best_buy_desc = f"促销窗口: {predicted_min_date} 前后，预计降至¥{predicted_min:.0f}"
        else:
            best_buy_desc = f"预计还有{drop_pct:.0f}%降价空间，可观望至{predicted_min_date}"

    elif drop_pct >= 5 and days_until_departure >= 7:
        # ── Moderate drop, some time → watch ──
        best_buy_desc = f"预计小幅下降至¥{predicted_min:.0f}，可观望至{predicted_min_date}"

    elif near_low:
        # ── Already near bottom → buy ──
        best_buy_desc = f"当前¥{current_price:.0f}接近历史最低¥{historical_min:.0f}，建议入手"

    elif rise_pct >= 5:
        # ── Strong upward trend → buy now ──
        if enough_time:
            best_buy_desc = f"价格预计上涨{rise_pct:.0f}%，建议{days_until_departure // 2}天内锁定"
        else:
            best_buy_desc = f"价格正在上涨（+{rise_pct:.0f}%），请尽快购买"

    elif rise_pct >= 3:
        # ── Mild upward trend → buy soon ──
        best_buy_desc = f"价格预计上涨{rise_pct:.0f}%，建议尽早入手"

    elif predicted_min < current_price and enough_time:
        # ── Slight drop, enough time → lazy watch ──
        best_buy_desc = f"价格稳定，可观望至{predicted_min_date}"

    else:
        # ── Stable → no strong signal ──
        if profile == "monopoly":
            best_buy_desc = f"竞争少航线，价格稳定，可随时购买"
        elif near_low:
            best_buy_desc = f"价格已接近底部，现在入手是不错的选择"
        else:
            best_buy_desc = ""  # no signal

    # Build Chart.js data
    n_hist = len(hist_prices)
    n_future = len(future_dates)
    gap = [None] * (n_hist - 1)

    chart_data = {
        "labels": hist_dates + future_dates,
        "datasets": [
            {
                "label": "历史价格",
                "data": hist_prices + [None] * n_future,
                "borderColor": "#3b82f6",
                "backgroundColor": "rgba(59, 130, 246, 0.08)",
                "fill": False,
                "tension": 0.3,
                "pointRadius": 2,
                "borderWidth": 2,
            },
            {
                "label": "预测价格",
                "data": gap + [hist_prices[-1]] + prediction_result["forecast"],
                "borderColor": "#ef4444",
                "backgroundColor": "rgba(239, 68, 68, 0.08)",
                "borderDash": [6, 4],
                "fill": False,
                "tension": 0.3,
                "pointRadius": 0,
                "borderWidth": 2,
            },
            {
                "label": "95%置信上限",
                "data": gap + [hist_prices[-1]] + prediction_result["upper"],
                "borderColor": "rgba(239, 68, 68, 0.25)",
                "backgroundColor": "rgba(239, 68, 68, 0.04)",
                "fill": "+1",
                "tension": 0.3,
                "pointRadius": 0,
                "borderWidth": 1,
            },
            {
                "label": "95%置信下限",
                "data": gap + [hist_prices[-1]] + prediction_result["lower"],
                "borderColor": "rgba(239, 68, 68, 0.25)",
                "backgroundColor": "rgba(239, 68, 68, 0.04)",
                "fill": False,
                "tension": 0.3,
                "pointRadius": 0,
                "borderWidth": 1,
            },
        ],
    }

    return {
        "departure": departure,
        "destination": destination,
        "departure_date": departure_date,
        "cabin_class": cabin_class,
        "days_until_departure": days_until_departure,
        "route_profile": profile,
        "route_profile_label": _PROFILE_LABELS.get(profile, profile),
        "route_description": route_info["description"],
        "model": prediction_result["model"],
        "current_price": round(current_price),
        "historical_min": round(historical_min),
        "predicted_min": round(predicted_min),
        "predicted_min_date": predicted_min_date,
        "predicted_max": round(predicted_max),
        "best_buy_window": best_buy_desc,
        "chart": {
            "labels": hist_dates + future_dates,
            "historical_prices": hist_prices + [None] * n_future,
            "forecast_prices": gap + [hist_prices[-1]] + prediction_result["forecast"],
            "lower_bound": gap + [hist_prices[-1]] + prediction_result["lower"],
            "upper_bound": gap + [hist_prices[-1]] + prediction_result["upper"],
        },
        "confidence_interval": "95%",
        "data_points": real_data_points,
        "data_points_total": len(valid_hist),
        "data_points_real": len(real_hist),
        "evaluation": prediction_result.get("evaluation", {}),
        "feature_importance": prediction_result.get("feature_importance", {}),
        "chart_data": chart_data,
        "stats": {
            "current_price": round(current_price),
            "historical_min": round(historical_min),
            "predicted_min": round(predicted_min),
            "predicted_min_date": predicted_min_date,
            "days_until_departure": days_until_departure,
        },
        "recommendation": _generate_recommendation(
            current_price, predicted_min, predicted_max,
            profile, days_until_departure, len(real_hist), len(valid_hist),
            best_buy_desc,
        ),
    }


def _generate_recommendation(
    current_price: float,
    predicted_min: float,
    predicted_max: float,
    profile: str,
    days_until_departure: int,
    real_points: int,
    total_points: int,
    best_buy: str = "",
) -> str:
    """Generate a specific, actionable buy/wait recommendation."""
    if current_price <= 0:
        return "暂无足够数据提供建议"

    drop_pct = ((current_price - predicted_min) / predicted_min * 100) if predicted_min > 0 else 0
    rise_pct = ((predicted_max - current_price) / current_price * 100) if current_price > 0 else 0

    # Confidence reflects both real and total data points
    if total_points < 3:
        conf_note = f"（仅 {total_points} 个数据点 + 航线模型估算，置信度较低）"
    elif real_points == 0:
        conf_note = f"（基于 {total_points} 个数据点，含 {total_points} 模拟数据，置信度中等）"
    elif real_points < 3:
        conf_note = f"（{total_points} 个数据点，其中 {real_points} 个真实抓取 + {total_points-real_points} 个历史，置信度中等）"
    elif real_points < 10:
        conf_note = f"（基于 {real_points} 个真实 + {total_points-real_points} 个历史数据，置信度较高）"
    else:
        conf_note = f"（基于 {real_points} 个真实数据点，置信度高）"

    recs = {
        "competitive": (
            f"✅ 竞争航线，建议等待 | 预计还有 {drop_pct:.0f}% 降价空间 | "
            f"最佳入手日 {best_buy}" if drop_pct > 3 and best_buy
            else f"📊 竞争航线 | 价格已接近底部，可入手 | {conf_note}"
        ),
        "moderate": (
            f"📊 价格稳定 | 预计波动 {abs(rise_pct):.0f}% 以内 | "
            f"建议提前 7-10 天购买 | {conf_note}"
        ),
        "monopoly": (
            f"⚠️ 航线竞争少，价格上涨趋势明确 | "
            f"建议尽早购买避免加价 | {conf_note}"
        ),
        "budget": (
            f"🎯 廉航航线，关注促销 | 预计有 {drop_pct:.0f}% 降价可能 | "
            f"{best_buy}" if best_buy
            else f"🎯 廉航航线 | 价格波动大，设置提醒捕捉低价 | {conf_note}"
        ),
        "holiday": (
            f"🔴 节假日出行！价格预计上涨 {rise_pct:.0f}% | "
            f"距出发 {days_until_departure} 天，尽早锁定 | {conf_note}"
        ),
        "offpeak": (
            f"💤 淡季出行 | 价格仍有下行空间 | "
            f"不急出手，可设置降价提醒 | {conf_note}"
        ),
    }

    return recs.get(profile, f"📊 建议关注价格走势 | {conf_note}")
