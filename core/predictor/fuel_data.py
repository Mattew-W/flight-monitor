"""
Flight Monitor — Aviation Fuel Price Data (City + Duration Based)
==================================================================

Provides jet fuel price index data that varies by:
  1. Departure/destination city (regional fuel price differences)
  2. Flight duration (longer flights = higher fuel cost sensitivity)
  3. Date (temporal trends + seasonal effects)

PDF Reference: §3.2 — "燃油价格的滞后效应与成本传导特征"

Key design:
  - Regional fuel price multipliers: oil-producing regions cheaper, remote regions premium
  - Duration-based cost-pass-through: longer flights more sensitive to fuel price changes
  - Interaction feature = regional_price × duration_hours × distance_factor
"""
import json
import logging
import math
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Baseline fuel prices by year (USD per barrel, Asia-Pacific ~avg) ──
FUEL_BASELINES: Dict[int, float] = {
    2019: 81.0,
    2020: 45.0,   # COVID crash
    2021: 74.0,   # recovery
    2022: 135.0,  # Ukraine war spike
    2023: 102.0,  # gradual decline
    2024: 95.0,
    2025: 88.0,
    2026: 92.0,
}

# ── Regional fuel price multipliers ──
# Oil-producing regions have cheaper fuel; remote/island regions have premium
# Multiplier applied to global baseline
REGION_FUEL_MULTIPLIERS: Dict[str, float] = {
    # 中国国内（基准）
    "China": 1.0,
    # 亚洲主要航空枢纽
    "EastAsia": 1.05,      # 日本、韩国（依赖进口）
    "SoutheastAsia": 1.08,  # 东南亚（部分进口）
    "SouthAsia": 1.10,      # 南亚（印度等，高油价）
    # 中东（产油国，燃油便宜）
    "MiddleEast": 0.85,
    # 欧洲
    "Europe": 1.12,         # 高税收
    "Russia": 0.90,         # 产油国
    # 北美
    "NorthAmerica": 1.08,
    # 大洋洲（远程运输成本）
    "Oceania": 1.15,
    # 非洲
    "Africa": 1.18,
    # 南美
    "SouthAmerica": 1.10,
}

# ── City → Region mapping ──
CITY_TO_REGION: Dict[str, str] = {
    # 中国
    "北京": "China", "上海": "China", "广州": "China", "深圳": "China",
    "成都": "China", "重庆": "China", "西安": "China", "昆明": "China",
    "杭州": "China", "南京": "China", "武汉": "China", "长沙": "China",
    "哈尔滨": "China", "沈阳": "China", "大连": "China", "青岛": "China",
    "郑州": "China", "乌鲁木齐": "China", "拉萨": "China", "厦门": "China",
    "福州": "China", "济南": "China", "天津": "China", "石家庄": "China",
    "太原": "China", "呼和浩特": "China", "长春": "China", "南昌": "China",
    "合肥": "China", "南宁": "China", "贵阳": "China", "兰州": "China",
    "银川": "China", "西宁": "China", "海口": "China", "三亚": "China",
    "香港": "China", "澳门": "China", "台北": "China",
    # 日韩
    "东京": "EastAsia", "大阪": "EastAsia", "名古屋": "EastAsia",
    "首尔": "EastAsia", "釜山": "EastAsia",
    # 东南亚
    "曼谷": "SoutheastAsia", "新加坡": "SoutheastAsia", "吉隆坡": "SoutheastAsia",
    "河内": "SoutheastAsia", "胡志明市": "SoutheastAsia", "马尼拉": "SoutheastAsia",
    "雅加达": "SoutheastAsia", "金边": "SoutheastAsia", "仰光": "SoutheastAsia",
    "普吉岛": "SoutheastAsia", "清迈": "SoutheastAsia", "琅勃拉邦": "SoutheastAsia",
    # 南亚
    "德里": "SouthAsia", "孟买": "SouthAsia", "班加罗尔": "SouthAsia",
    "加尔各答": "SouthAsia", "金奈": "SouthAsia",
    # 中东
    "迪拜": "MiddleEast", "多哈": "MiddleEast", "阿布扎比": "MiddleEast",
    "利雅得": "MiddleEast", "科威特": "MiddleEast", "麦纳麦": "MiddleEast",
    # 欧洲
    "伦敦": "Europe", "巴黎": "Europe", "法兰克福": "Europe",
    "阿姆斯特丹": "Europe", "罗马": "Europe", "米兰": "Europe",
    "马德里": "Europe", "巴塞罗那": "Europe", "慕尼黑": "Europe",
    "柏林": "Europe", "维也纳": "Europe", "苏黎世": "Europe",
    "莫斯科": "Russia", "伊斯坦布尔": "Europe", "雅典": "Europe",
    "哥本哈根": "Europe", "斯德哥尔摩": "Europe", "都柏林": "Europe",
    "里斯本": "Europe", "赫尔辛基": "Europe",
    # 北美
    "纽约": "NorthAmerica", "洛杉矶": "NorthAmerica", "旧金山": "NorthAmerica",
    "芝加哥": "NorthAmerica", "波士顿": "NorthAmerica", "华盛顿": "NorthAmerica",
    "西雅图": "NorthAmerica", "迈阿密": "NorthAmerica", "多伦多": "NorthAmerica",
    "温哥华": "NorthAmerica", "蒙特利尔": "NorthAmerica", "拉斯维加斯": "NorthAmerica",
    "奥兰多": "NorthAmerica", "亚特兰大": "NorthAmerica", "达拉斯": "NorthAmerica",
    "休斯顿": "NorthAmerica",
    # 大洋洲
    "悉尼": "Oceania", "墨尔本": "Oceania", "布里斯班": "Oceania",
    "奥克兰": "Oceania", "珀斯": "Oceania", "阿德莱德": "Oceania",
    # 非洲
    "特拉维夫": "Africa", "开罗": "Africa", "约翰内斯堡": "Africa",
    "开普敦": "Africa", "内罗毕": "Africa", "亚的斯亚贝巴": "Africa",
    # 南美
    "圣保罗": "SouthAmerica", "里约热内卢": "SouthAmerica",
    "布宜诺斯艾利斯": "SouthAmerica", "利马": "SouthAmerica",
    "圣地亚哥": "SouthAmerica",
}

# ── Duration-based fuel sensitivity coefficients ──
# Longer flights have higher fuel cost as % of ticket price
# This affects how strongly fuel price changes translate to ticket price changes
DURATION_SENSITIVITY: Dict[str, float] = {
    "short": 0.15,    # < 3 hours: fuel is ~15% of cost
    "medium": 0.25,   # 3-6 hours: fuel is ~25% of cost
    "long": 0.35,     # 6-10 hours: fuel is ~35% of cost
    "ultra_long": 0.45,  # > 10 hours: fuel is ~45% of cost
}

# Monthly seasonal adjustment factors
MONTHLY_SEASONAL: Dict[int, float] = {
    1: 1.06, 2: 1.04, 3: 1.02,
    4: 0.98, 5: 0.97, 6: 0.96,
    7: 0.97, 8: 0.98, 9: 1.00,
    10: 1.02, 11: 1.04, 12: 1.06,
}

# ── Default cache path & TTL ──
DEFAULT_CACHE_PATH = "config/fuel_cache.json"
CACHE_TTL_HOURS = 24


def _get_region(city: str) -> str:
    """Get fuel price region for a city."""
    return CITY_TO_REGION.get(city, "China")  # Default to China


def _get_duration_category(duration_mins: int) -> str:
    """Classify flight duration into sensitivity category."""
    hours = duration_mins / 60.0
    if hours < 3:
        return "short"
    elif hours < 6:
        return "medium"
    elif hours < 10:
        return "long"
    else:
        return "ultra_long"


class FuelPriceProvider:
    """Provides jet fuel price with city + duration + date awareness.

    Usage:
        provider = FuelPriceProvider("config/fuel_cache.json")
        
        # Get regional fuel price
        price = provider.get_regional_fuel_price("北京", datetime(2026, 7, 1))
        
        # Get fuel interaction feature (city + duration + date)
        interaction = provider.get_fuel_interaction(
            "北京", "上海", duration_mins=150, date=datetime(2026, 7, 1)
        )
    """

    def __init__(self, cache_path: Optional[str] = None):
        self.cache_path = cache_path or DEFAULT_CACHE_PATH
        self._cache: Dict = {}
        self._load_cache()

    # ── Public API ────────────────────────────────────────

    def get_regional_fuel_price(
        self, city: str, date: datetime, window_days: int = 30
    ) -> float:
        """Get fuel price for a specific city/region.

        Args:
            city: Departure or arrival city name.
            date: Target date.
            window_days: Rolling window for smoothing.

        Returns:
            Estimated fuel price in USD per barrel for that region.
        """
        date_key = date.strftime("%Y-%m-%d")
        region = _get_region(city)
        window_key = f"rolling_{region}_{window_days}d"

        # Check cache first
        if self._is_cache_fresh() and window_key in self._cache:
            cached = self._cache[window_key]
            closest = self._closest_key(cached, date_key)
            if closest:
                return float(cached[closest])

        # Fallback: baseline × regional multiplier × seasonal
        return self._estimate_regional_price(region, date)

    def get_fuel_interaction(
        self,
        departure_city: str,
        destination_city: str,
        duration_mins: int,
        date: datetime,
        window_days: int = 30,
    ) -> float:
        """Compute the PDF §3.2 fuel interaction feature (city + duration based).

        This captures:
        1. Regional fuel price differences (oil-producing vs importing regions)
        2. Flight duration sensitivity (longer flights = more fuel cost exposure)
        3. Cost-pass-through effect (airlines hedge, so use rolling average)

        Formula:
            interaction = (regional_price / global_baseline) × duration_hours × sensitivity_coeff

        Args:
            departure_city: Departure city name.
            destination_city: Destination city name.
            duration_mins: Flight duration in minutes.
            date: Flight date.
            window_days: Rolling window (30 or 90 per PDF).

        Returns:
            Normalized interaction value (≈1.0 for average route).
        """
        # Use departure city as primary (fuel uplifted at departure)
        # For round-trip pricing, could average both cities
        dep_region = _get_region(departure_city)
        arr_region = _get_region(destination_city)
        
        # Weighted: 60% departure, 40% arrival (fuel bought at both ends)
        dep_price = self.get_regional_fuel_price(departure_city, date, window_days)
        arr_price = self.get_regional_fuel_price(destination_city, date, window_days)
        blended_price = dep_price * 0.6 + arr_price * 0.4

        # Global baseline for normalization
        global_baseline = self._get_baseline(date.year)
        if global_baseline <= 0:
            return 0.0

        # Duration in hours (subtract taxi time)
        adjusted_mins = max(30, duration_mins)
        duration_hours = (adjusted_mins - 30) / 60.0 if adjusted_mins > 30 else duration_mins / 60.0

        # Duration sensitivity: longer flights more affected by fuel price
        duration_cat = _get_duration_category(duration_mins)
        sensitivity = DURATION_SENSITIVITY[duration_cat]

        # Interaction: (regional_price / global_baseline) × duration_hours × sensitivity
        # ≈1.0 means "average fuel burden"; >1 means "elevated fuel cost"
        fuel_ratio = blended_price / global_baseline
        interaction = fuel_ratio * duration_hours * sensitivity

        return round(interaction, 4)

    def get_fuel_price(self, date: datetime, window_days: int = 30) -> float:
        """Get global average fuel price (backward compatible)."""
        return self._estimate_from_baseline(date, window_days)

    def get_fuel_rolling_interaction(
        self, date: datetime, duration_mins: int, window_days: int = 30
    ) -> float:
        """Legacy interface: fuel interaction without city specificity."""
        fuel_price = self.get_fuel_price(date, window_days)
        baseline = self._get_baseline(date.year)
        if baseline <= 0:
            return 0.0

        adjusted_mins = max(30, duration_mins)
        duration_hours = (adjusted_mins - 30) / 60.0 if adjusted_mins > 30 else 0
        if duration_hours <= 0:
            duration_hours = duration_mins / 60.0

        fuel_ratio = fuel_price / baseline
        duration_cat = _get_duration_category(duration_mins)
        sensitivity = DURATION_SENSITIVITY[duration_cat]
        interaction = fuel_ratio * duration_hours * sensitivity

        return round(interaction, 4)

    def update_cache(self, prices: Dict[str, float]):
        """Update the cache with new fuel price data."""
        self._cache["raw_prices"] = self._cache.get("raw_prices", {})
        self._cache["raw_prices"].update(prices)

        for window_days in (30, 90):
            self._cache[f"rolling_{window_days}d"] = self._compute_rolling(
                self._cache["raw_prices"], window_days
            )

        self._cache["last_updated"] = time.time()
        self._save_cache()
        logger.info("Fuel cache updated: %d new entries", len(prices))

    # ── Internal helpers ──────────────────────────────────

    def _estimate_regional_price(self, region: str, date: datetime) -> float:
        """Estimate fuel price for a region on a date."""
        year = date.year
        month = date.month

        if year in FUEL_BASELINES:
            baseline = FUEL_BASELINES[year]
        else:
            known_years = sorted(FUEL_BASELINES.keys())
            baseline = FUEL_BASELINES[known_years[-1]]

        regional_mult = REGION_FUEL_MULTIPLIERS.get(region, 1.0)
        seasonal = MONTHLY_SEASONAL.get(month, 1.0)
        price = baseline * regional_mult * seasonal

        # Deterministic jitter
        jitter = math.sin(hash(f"{region}_{date.strftime('%Y-%m-%d')}") % 1000) * 0.01
        price *= (1.0 + jitter)

        return round(price, 2)

    def _estimate_from_baseline(self, date: datetime, window_days: int) -> float:
        """Estimate global average fuel price."""
        year = date.year
        month = date.month

        if year in FUEL_BASELINES:
            baseline = FUEL_BASELINES[year]
        else:
            known_years = sorted(FUEL_BASELINES.keys())
            baseline = FUEL_BASELINES[known_years[-1]]

        seasonal = MONTHLY_SEASONAL.get(month, 1.0)
        price = baseline * seasonal

        jitter = math.sin(hash(date.strftime("%Y-%m-%d")) % 1000) * 0.01
        price *= (1.0 + jitter)

        return round(price, 2)

    def _get_baseline(self, year: int) -> float:
        """Get baseline fuel price for a year."""
        if year in FUEL_BASELINES:
            return FUEL_BASELINES[year]
        known_years = sorted(FUEL_BASELINES.keys())
        if year < known_years[0]:
            return FUEL_BASELINES[known_years[0]]
        return FUEL_BASELINES[known_years[-1]]

    def _compute_rolling(
        self, raw: Dict[str, float], window_days: int
    ) -> Dict[str, float]:
        """Compute rolling average from raw daily prices."""
        if not raw:
            return {}

        sorted_dates = sorted(raw.keys())
        result = {}

        for target_str in sorted_dates:
            target = datetime.strptime(target_str, "%Y-%m-%d")
            window_start = target - timedelta(days=window_days - 1)

            window_prices = []
            for d_str in sorted_dates:
                d = datetime.strptime(d_str, "%Y-%m-%d")
                if window_start <= d <= target:
                    window_prices.append(raw[d_str])
                elif d > target:
                    break

            if window_prices:
                result[target_str] = round(
                    sum(window_prices) / len(window_prices), 2
                )

        return result

    @staticmethod
    def _closest_key(dct: Dict[str, float], target_key: str) -> Optional[str]:
        """Find the closest (or exact) key to target_key."""
        if target_key in dct:
            return target_key
        if not dct:
            return None

        target = datetime.strptime(target_key, "%Y-%m-%d")
        best = None
        best_date = None
        for key in dct:
            key_date = datetime.strptime(key, "%Y-%m-%d")
            if key_date <= target and (best_date is None or key_date > best_date):
                best = key
                best_date = key_date
        return best

    def _is_cache_fresh(self) -> bool:
        """Check if cache is still valid (within TTL)."""
        if not self._cache.get("last_updated"):
            return False
        age_hours = (time.time() - self._cache["last_updated"]) / 3600
        return age_hours < CACHE_TTL_HOURS

    def _load_cache(self):
        """Load cache from disk."""
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Failed to load fuel cache: %s", e)
                self._cache = {}
        else:
            self._cache = {}

    def _save_cache(self):
        """Save cache to disk."""
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except IOError as e:
            logger.warning("Failed to save fuel cache: %s", e)
