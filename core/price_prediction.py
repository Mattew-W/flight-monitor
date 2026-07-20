"""
Flight Monitor - Price Prediction Engine v3
=============================================

Route-aware prediction combining:
  1. Indian flight data priors (universal behavioral patterns)
  2. PDF design guide feature engineering
  3. Scikit-learn ensemble models (GradientBoosting + RandomForest + Ridge)
  4. Walk-forward validation (no data leakage)
  5. Bayesian blending (prior + online model)

Backward compatible: generate_prediction_chart() keeps the same signature.
"""
import hashlib
import logging
import math
import random
import statistics
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)


def _stable_seed(*parts):
    """Stable integer seed from string parts (md5, not Python's randomized hash)."""
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.md5(raw.encode("utf-8")).hexdigest()[:8], 16)

# ── New predictor (v3) ────────────────────────────────────
from .predictor import PricePredictorV3, extract_features

# Module-level singleton (lazy init)
_predictor_v3: Optional[PricePredictorV3] = None


def _get_predictor() -> Optional[PricePredictorV3]:
    """Lazy-init the v3 predictor singleton."""
    global _predictor_v3
    if _predictor_v3 is None:
        try:
            import os
            # Look for indian_priors.json in config/
            config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
            priors_path = os.path.join(config_dir, "indian_priors.json")
            if os.path.exists(priors_path):
                _predictor_v3 = PricePredictorV3(indian_priors_path=priors_path)
                logger.info("PricePredictorV3 initialized with Indian priors")
            else:
                logger.warning(f"indian_priors.json not found at {priors_path}, using fallback")
                _predictor_v3 = PricePredictorV3()
        except Exception as e:
            logger.warning(f"Failed to init PricePredictorV3: {e}")
            _predictor_v3 = None
    return _predictor_v3


# =====================================================================
#  ROUTE CLASSIFICATION (legacy compatibility)
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

# Chinese holiday rules (approximate Gregorian offsets for lunar festivals)
_HOLIDAY_RULES = [
    (1, 28, "春节", 7, 10),
    (4, 5, "清明", 3, 2),
    (5, 1, "五一", 5, 3),
    (5, 31, "端午", 3, 2),
    (7, 1, "暑假", 62, 20),
    (9, 15, "中秋+国庆", 24, 14),
    (12, 31, "元旦", 3, 2),
]


class HolidayManager:
    """Dynamic holiday engine — no hardcoded year."""
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


def _classify_route(departure: str, destination: str, dep_date: datetime) -> Dict:
    """Classify a route into one of 6 pricing profile types."""
    route_key = (departure, destination)

    # 1. Holiday check first (overrides everything)
    for start, end, name in HolidayManager.get_holidays(dep_date.year):
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

    # 5. International / long-haul
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
#  HISTORICAL PRICES (legacy, kept for compatibility)
# =====================================================================

def get_historical_prices(db, query_id: int, days_back: int = 30,
                          real_only: bool = True,
                          include_mock: bool = False) -> List[Dict]:
    """Get rich historical price records for ML modeling or chart display.

    Uses the public database accessor get_daily_cheapest_records() to
    preserve flight-level metadata (departure_time, sub_class, etc.).
    """
    try:
        rows = db.get_daily_cheapest_records(
            query_id=query_id,
            real_only=real_only,
            include_mock=include_mock,
            limit=500,
        )
        if not rows:
            return []

        by_date = {}
        for r in rows:
            d = r["date"]
            if d not in by_date:
                by_date[d] = {
                    "date": d,
                    "price": float(r["price"]),
                    "min_price": float(r["price"]),
                    "avg_price": float(r["price"]),
                    "departure_time": (r.get("departure_time") or ""),
                    "sub_class": (r.get("sub_class", "")),
                    "seat_inventory": int(r.get("seat_inventory", 9)),
                    "stops": int(r.get("stops", 0)),
                }
        return sorted(by_date.values(), key=lambda x: x["date"])
    except Exception as e:
        logger.error(f"Error getting historical prices: {e}")
        return []


# =====================================================================
#  MAIN CHART GENERATION (v3 integration)
# =====================================================================

def generate_prediction_chart(
    db,
    query_id: int,
    departure: str,
    destination: str,
    departure_date: str,
    cabin_class: str = "economy",
) -> Dict:
    """Generate a route-aware price prediction chart.

    Uses the new PricePredictorV3 if available, falls back gracefully.
    Returns the same format as v2 for backward compatibility.
    """
    # Parse departure date
    try:
        dep_date = datetime.strptime(departure_date, "%Y-%m-%d")
    except ValueError:
        try:
            dep_date = datetime.strptime(departure_date, "%Y-%m-%dT%H:%M:%S")
            departure_date = dep_date.strftime("%Y-%m-%d")
        except ValueError:
            return {"error": "Invalid departure date", "departure_date": departure_date,
                    "days_until_departure": 0}

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_until_departure = max(1, (dep_date - today).days)

    if dep_date < today:
        return {
            "error": "出发日期已过，无法生成预测",
            "departure_date": departure_date,
            "days_until_departure": 0,
        }

    # Get historical data
    historical = get_historical_prices(db, query_id, days_back=30,
                                       real_only=False, include_mock=True)
    real_hist = get_historical_prices(db, query_id, days_back=30,
                                     real_only=False, include_mock=False)
    valid_hist = [h for h in historical if h.get("avg_price", 0) > 0 or h.get("min_price", 0) > 0]

    if not valid_hist:
        return {
            "error": "无有效价格数据，请先进行一次搜索",
            "departure_date": departure_date,
            "days_until_departure": days_until_departure,
        }

    current_price = valid_hist[-1].get("avg_price", 0) or valid_hist[-1].get("min_price", 0)

    # ── Try new predictor v3 first ──
    predictor = _get_predictor()
    use_v3 = predictor is not None and len(valid_hist) >= 3

    if use_v3:
        try:
            return _generate_with_v3(
                predictor, db, query_id, departure, destination, departure_date,
                cabin_class, dep_date, days_until_departure, current_price,
                valid_hist, real_hist, historical,
            )
        except Exception as e:
            logger.warning(f"v3 predictor failed ({e}), falling back to v2")

    # ── Fallback: v2 logic (simplified) ──
    return _generate_with_v2(
        db, query_id, departure, destination, departure_date,
        cabin_class, dep_date, days_until_departure, current_price,
        valid_hist, real_hist, historical,
    )


def _generate_with_v3(
    predictor, db, query_id, departure, destination, departure_date,
    cabin_class, dep_date, days_until_departure, current_price,
    valid_hist, real_hist, historical,
) -> Dict:
    """Generate chart using the new PricePredictorV3."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Classify route
    route_info = _classify_route(departure, destination, dep_date)
    profile = route_info["profile"]

    # Build holidays list for predictor
    holidays = []
    for start, end, _ in HolidayManager.get_holidays(dep_date.year):
        holidays.append((start, end))

    # Format history for predictor
    online_history = []
    for h in valid_hist:
        online_history.append({
            "price": h.get("avg_price", 0),
            "date": h.get("date", ""),
            "departure_time": h.get("departure_time", ""),
            "sub_class": h.get("sub_class", ""),
            "seat_inventory": h.get("seat_inventory", 9),
            "stops": h.get("stops", 0),
            "is_mock": False,
        })

    # Build flights snapshot (from latest valid_hist record)
    flights = [{
        "price": current_price,
        "departure_time": valid_hist[-1].get("departure_time", ""),
        "airline": "Unknown",
        "stops": valid_hist[-1].get("stops", 0),
    }]

    # Generate prediction
    result = predictor.predict(
        flights=flights,
        online_history=online_history,
        days_ahead=days_until_departure,
        departure_city=departure,
        destination_city=destination,
        departure_date=departure_date,
        cabin_class=cabin_class,
        holidays=holidays,
    )

    # The predict() function already applies _days_to_departure_modifier internally
    # to base_price. We must NOT apply it again (double-counting caused extreme
    # 37%+ price inflation near departure). Instead we build a gentle curve:
    # for each future day we compute the *relative* modifier change from today's
    # value and apply it as a small adjustment factor around 1.0.
    base_price = result["forecast"]
    base_lower = result["lower_ci"]
    base_upper = result["upper_ci"]

    forecast = []
    lower_ci = []
    upper_ci = []
    for d in range(1, days_until_departure + 1):
        days_left = days_until_departure - d + 1
        mod_future = predictor._days_to_departure_modifier(days_left)
        mod_today = predictor._days_to_departure_modifier(days_until_departure)
        # mod_future / mod_today shows how much the curve bends.
        # Without the internal predict() application, this ratio IS the price curve.
        # Since predict() already applied mod_today, we need DIFF from that baseline:
        # a ratio of 1.0 means price unchanged, >1.0 means higher, <1.0 means lower.
        # Clamp to avoid extreme swings (data noise shouldn't override model).
        ratio = mod_future / max(mod_today, 0.01)
        ratio = max(0.85, min(1.15, ratio))  # clamp within ±15%
        forecast.append(round(base_price * ratio))
        # Symmetric CI: expand both bands by sqrt(ci_expansion) (avoids the old
        # problem where lower shrank toward 0 while upper ballooned).
        ci_expansion = math.sqrt(1.0 + (d / max(days_until_departure, 1)))
        lower_ci.append(round(base_lower * ratio / ci_expansion))
        upper_ci.append(round(base_upper * ratio * ci_expansion))

    # Build future dates
    future_dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d")
                    for i in range(1, days_until_departure + 1)]

    # Pad/truncate forecast to match days_until_departure
    if len(forecast) < days_until_departure:
        forecast.extend([forecast[-1]] * (days_until_departure - len(forecast)))
        lower_ci.extend([lower_ci[-1]] * (days_until_departure - len(lower_ci)))
        upper_ci.extend([upper_ci[-1]] * (days_until_departure - len(upper_ci)))

    # Generate recommendation
    predicted_min = min(forecast) if forecast else current_price
    predicted_max = max(forecast) if forecast else current_price
    predicted_min_date = future_dates[forecast.index(predicted_min)] if forecast else ""
    historical_min = min(h.get("avg_price", 0) for h in valid_hist) if valid_hist else current_price

    best_buy = _generate_best_buy_desc(
        current_price, predicted_min, predicted_max,
        profile, days_until_departure, historical_min,
    )

    # Build chart data (same format as v2 for frontend compatibility)
    hist_dates = [h["date"] for h in historical]
    hist_prices = [h.get("avg_price", 0) for h in historical]
    n_hist = len(hist_prices)
    n_future = days_until_departure
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
                "data": gap + [hist_prices[-1]] + forecast[:n_future],
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
                "data": gap + [hist_prices[-1]] + upper_ci[:n_future],
                "borderColor": "rgba(239, 68, 68, 0.25)",
                "backgroundColor": "rgba(239, 68, 68, 0.04)",
                "fill": "+1",
                "tension": 0.3,
                "pointRadius": 0,
                "borderWidth": 1,
            },
            {
                "label": "95%置信下限",
                "data": gap + [hist_prices[-1]] + lower_ci[:n_future],
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
        "model": result.get("model", "v3 Predictor"),
        "current_price": round(current_price),
        "historical_min": round(historical_min),
        "predicted_min": round(predicted_min),
        "predicted_min_date": predicted_min_date,
        "predicted_max": round(predicted_max),
        "best_buy_window": best_buy,
        "chart": {
            "labels": hist_dates + future_dates,
            "historical_prices": hist_prices + [None] * n_future,
            "forecast_prices": gap + [hist_prices[-1]] + forecast[:n_future],
            "lower_bound": gap + [hist_prices[-1]] + lower_ci[:n_future],
            "upper_bound": gap + [hist_prices[-1]] + upper_ci[:n_future],
        },
        "confidence_interval": "95%",
        "data_points": len([h for h in valid_hist if h.get("avg_price", 0) > 0]),
        "data_points_total": len(valid_hist),
        "data_points_real": len(real_hist),
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
            best_buy,
        ),
        # v3 specific fields
        "_v3_data_weight": result.get("data_weight", 0),
        "_v3_model": result.get("model", ""),
    }


def _generate_with_v2(
    db, query_id, departure, destination, departure_date,
    cabin_class, dep_date, days_until_departure, current_price,
    valid_hist, real_hist, historical,
) -> Dict:
    """Fallback v2 generation (simplified from original)."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    route_info = _classify_route(departure, destination, dep_date)
    profile = route_info["profile"]

    # Use simplified statistical forecast
    hist_prices = [h.get("avg_price", 0) for h in historical]
    valid_prices = [p for p in hist_prices if p > 0]

    if not valid_prices:
        return {
            "error": "无有效价格数据",
            "departure_date": departure_date,
            "days_until_departure": days_until_departure,
        }

    # Simple linear + seasonality forecast
    forecast = _simple_forecast(valid_prices, days_until_departure, profile)

    # Confidence intervals — widen with forecast horizon
    future_dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d")
                    for i in range(1, days_until_departure + 1)]
    lower = []
    upper = []
    for i, f in enumerate(forecast):
        ci_expansion = math.sqrt(1.0 + (i + 1) / max(days_until_departure, 1))
        lower.append(max(0, round(f * 0.8 / ci_expansion)))
        upper.append(round(f * 1.2 * ci_expansion))

    predicted_min = min(forecast) if forecast else current_price
    predicted_max = max(forecast) if forecast else current_price
    historical_min = min(valid_prices)
    predicted_min_date = future_dates[forecast.index(predicted_min)] if forecast else ""

    best_buy = _generate_best_buy_desc(
        current_price, predicted_min, predicted_max,
        profile, days_until_departure, historical_min,
    )

    hist_dates = [h["date"] for h in historical]
    n_hist = len(hist_prices)
    gap = [None] * (n_hist - 1)

    chart_data = {
        "labels": hist_dates + future_dates,
        "datasets": [
            {
                "label": "历史价格",
                "data": hist_prices + [None] * len(future_dates),
                "borderColor": "#3b82f6",
                "backgroundColor": "rgba(59, 130, 246, 0.08)",
                "fill": False,
                "tension": 0.3,
                "pointRadius": 2,
                "borderWidth": 2,
            },
            {
                "label": "预测价格",
                "data": gap + [hist_prices[-1]] + forecast,
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
                "data": gap + [hist_prices[-1]] + upper,
                "borderColor": "rgba(239, 68, 68, 0.25)",
                "backgroundColor": "rgba(239, 68, 68, 0.04)",
                "fill": "+1",
                "tension": 0.3,
                "pointRadius": 0,
                "borderWidth": 1,
            },
            {
                "label": "95%置信下限",
                "data": gap + [hist_prices[-1]] + lower,
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
        "model": "Statistical Baseline (v2 fallback)",
        "current_price": round(current_price),
        "historical_min": round(historical_min),
        "predicted_min": round(predicted_min),
        "predicted_min_date": predicted_min_date,
        "predicted_max": round(predicted_max),
        "best_buy_window": best_buy,
        "chart": {
            "labels": hist_dates + future_dates,
            "historical_prices": hist_prices + [None] * len(future_dates),
            "forecast_prices": gap + [hist_prices[-1]] + forecast,
            "lower_bound": gap + [hist_prices[-1]] + lower,
            "upper_bound": gap + [hist_prices[-1]] + upper,
        },
        "confidence_interval": "95%",
        "data_points": len(valid_prices),
        "data_points_total": len(valid_hist),
        "data_points_real": len(real_hist),
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
            best_buy,
        ),
    }


def _simple_forecast(prices: List[float], days_ahead: int, profile: str) -> List[float]:
    """Fallback: simple linear + profile-based shape."""
    if not prices:
        return [0] * days_ahead

    current = prices[-1]
    n = len(prices)

    # Linear regression
    xs = list(range(n))
    slope, intercept = _linear_regression(xs, prices)

    forecast = []
    for d in range(1, days_ahead + 1):
        base = intercept + slope * (n - 1 + d)
        # Apply profile modifier
        if profile == "holiday":
            base *= 1 + 0.02 * d
        elif profile == "monopoly":
            base *= 1 + 0.005 * d
        elif profile == "competitive":
            base *= 1 - 0.002 * d
        forecast.append(max(0, round(base)))

    return forecast


def _compute_residual_std(ys: List[float], slope: float, intercept: float) -> float:
    """Compute standard deviation of residuals from a linear fit."""
    if len(ys) < 2:
        return 1.0  # min clamp
    residuals = []
    for i, y in enumerate(ys):
        predicted = slope * i + intercept
        residuals.append(y - predicted)
    mean_sq = sum(r * r for r in residuals) / len(residuals)
    return max(math.sqrt(mean_sq), 1.0)  # min clamp to 1.0


def _wma_forecast(prices: List[float], days_ahead: int) -> Tuple[List[float], float]:
    """Weighted moving average forecast."""
    if not prices:
        return [0.0] * days_ahead, 0.0
    if len(prices) == 1:
        return [prices[0]] * days_ahead, 0.0

    # Weighted average with linearly increasing weights
    n = len(prices)
    weights = list(range(1, n + 1))
    total_w = sum(weights)
    wma = sum(p * w for p, w in zip(prices, weights)) / total_w

    # Trend strength (0-1)
    if n >= 2:
        recent = prices[-3:]
        if len(recent) >= 2:
            diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
            avg_diff = sum(diffs) / len(diffs)
            strength = min(abs(avg_diff) / (wma + 1), 1.0)
        else:
            strength = 0.0
    else:
        strength = 0.0

    # Project forward
    forecast = []
    for i in range(days_ahead):
        forecast.append(wma)

    return forecast, strength


def _ci_bands(forecast: List[float], residual_std: float, current_price: float,
              days_ahead: int) -> Tuple[List[float], List[float]]:
    """Generate confidence interval bands that widen over time."""
    lower = []
    upper = []
    for i, f in enumerate(forecast):
        # Band width grows with sqrt of time
        width = residual_std * math.sqrt(i + 1) * 1.96
        lower.append(f - width)
        upper.append(f + width)
    return lower, upper


def _linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """Simple linear regression."""
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


# =====================================================================
#  RECOMMENDATION ENGINE
# =====================================================================

def _generate_best_buy_desc(
    current_price: float,
    predicted_min: float,
    predicted_max: float,
    profile: str,
    days_until_departure: int,
    historical_min: float,
) -> str:
    """Generate buy/wait recommendation."""
    if current_price <= 0:
        return ""

    drop_pct = (current_price - predicted_min) / current_price * 100
    rise_pct = (predicted_max - current_price) / current_price * 100
    near_low = current_price <= historical_min * 1.05
    enough_time = days_until_departure >= 14

    if days_until_departure <= 3:
        return f"距起飞仅{days_until_departure}天，建议立即购买"

    if profile == "holiday":
        if enough_time:
            return f"节假日前{rise_pct:.0f}%涨幅预期，建议尽快锁定价格"
        return "节假日出行，价格持续高位，请尽快购买"

    if profile == "monopoly" and rise_pct > 2:
        return f"航线竞争少，价格预计上涨{rise_pct:.0f}%，建议尽早入手"

    if drop_pct >= 10 and enough_time:
        return f"预计还有{drop_pct:.0f}%降价空间，可观望"

    if drop_pct >= 5 and days_until_departure >= 7:
        return f"预计小幅下降，可观望"

    if near_low:
        return f"当前¥{current_price:.0f}接近历史最低，建议入手"

    if rise_pct >= 5:
        return f"价格预计上涨{rise_pct:.0f}%，建议尽早锁定"

    return ""


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

    conf_note = f"（基于{total_points}个数据点）"

    recs = {
        "competitive": f"✅ 竞争航线，建议关注降价 | {conf_note}",
        "moderate": f"📊 价格稳定，建议提前7-10天购买 | {conf_note}",
        "monopoly": f"⚠️ 竞争少航线，建议尽早购买 | {conf_note}",
        "budget": f"🎯 廉航航线，关注促销 | {conf_note}",
        "holiday": f"🔴 节假日前，建议尽快锁定价格 | {conf_note}",
        "offpeak": f"💤 淡季出行，不急出手 | {conf_note}",
    }

    return recs.get(profile, f"📊 建议关注价格走势 | {conf_note}")


# =====================================================================
#  PROFILE LABELS
# =====================================================================

_PROFILE_LABELS = {
    "competitive": "竞争激烈 — 降价窗口",
    "moderate": "温和竞争 — 波动不大",
    "monopoly": "有限执飞 — 持续上涨",
    "budget": "廉航主导 — 关注促销",
    "holiday": "节假日高峰 — 尽早购买",
    "offpeak": "淡季长线 — 不急出手",
}

# Legacy compatibility
HOLIDAYS_2026 = HolidayManager.get_holidays(2026)


# =====================================================================
#  LEGACY FORECAST FUNCTIONS (used by routes.py /api/manual_predict)
# =====================================================================

def arima_forecast(prices: List[float], days_ahead: int) -> Dict:
    """Simple exponential smoothing forecast (kept for backward compatibility)."""

    n = len(prices)
    if n < 3:
        return _empty_forecast(days_ahead)

    # Weighted moving average with exponential decay
    alpha = 0.3
    weights = [alpha * (1 - alpha) ** (n - 1 - i) for i in range(n)]
    weighted_avg = sum(p * w for p, w in zip(prices, weights)) / sum(weights)

    # Linear trend from last 7 points
    recent = prices[-7:] if n >= 7 else prices
    slope = (recent[-1] - recent[0]) / max(len(recent) - 1, 1)

    forecast = []
    lower = []
    upper = []
    base = weighted_avg

    for d in range(1, days_ahead + 1):
        value = max(0, base + slope * d)
        forecast.append(round(value))
        # CI widens with sqrt of time
        ci_expansion = math.sqrt(1.0 + d / max(days_ahead, 1))
        lower.append(max(0, round(value * 0.8 / ci_expansion)))
        upper.append(round(value * 1.2 * ci_expansion))

    return {
        "forecast": forecast,
        "lower": lower,
        "upper": upper,
        "model": "加权移动平均 (forecast)",
    }


def data_driven_forecast(prices: List[float], days_ahead: int, profile: str) -> Dict:
    """Profile-weighted forecast combining trend + seasonality + profile modifiers."""

    n = len(prices)
    if n < 5:
        return arima_forecast(prices, days_ahead)

    current = prices[-1]

    # Linear regression on log prices
    xs = list(range(n))
    log_prices = [math.log1p(max(p, 1)) for p in prices]
    slope, intercept = _linear_regression(xs, log_prices)

    # Profile-specific modifiers (drift is daily log-return, noise is daily vol)
    # Drift values are conservative to prevent exponential explosion
    profile_modifiers = {
        "competitive": (0.0, -0.003, 0.08),   # (floor, drift, noise_mult)
        "moderate": (0.0, 0.001, 0.06),
        "monopoly": (0.0, 0.004, 0.06),
        "budget": (0.0, -0.002, 0.10),
        "holiday": (0.0, 0.006, 0.08),
        "offpeak": (0.0, -0.001, 0.06),
    }
    floor, drift, noise = profile_modifiers.get(profile, (0.0, 0.0, 0.08))

    # Generate future log prices
    # Use _stable_seed (md5-based) instead of built-in hash() which is
    # randomized per process — otherwise same input gives different forecasts.
    rng = random.Random(_stable_seed(profile, prices[-1], n))
    forecast = []
    median_price = statistics.median(prices)
    for d in range(1, days_ahead + 1):
        log_val = intercept + slope * (n - 1 + d) + drift * d
        jitter = rng.gauss(0, noise)
        predicted = max(0, math.exp(log_val + jitter))
        # Clip each point to prevent exponential explosion
        predicted = max(median_price * 0.4, min(median_price * 2.0, predicted))
        forecast.append(round(predicted))

    # CI bands widen with forecast horizon (symmetric, gentle expansion)
    lower = []
    upper = []
    for i, f in enumerate(forecast):
        ci_expansion = 1.0 + 0.15 * math.sqrt(1.0 + (i + 1) / max(days_ahead, 1))
        lower.append(max(0, round(f / ci_expansion)))
        upper.append(round(f * ci_expansion))

    return {
        "forecast": forecast,
        "lower": lower,
        "upper": upper,
        "model": f"数据驱动 ({profile})",
    }


def _empty_forecast(days_ahead: int) -> Dict:
    """Return empty forecast structure."""
    return {
        "forecast": [0] * days_ahead,
        "lower": [0] * days_ahead,
        "upper": [0] * days_ahead,
        "model": "无数据",
    }
