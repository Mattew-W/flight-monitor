# 航班价格预测模型 v3 — 设计框架文档（给 DS 实现参考）

> 核心原则：PDF 中明确"必须做"的特征全部补齐，同时修复现有代码中的 bug。
> 所有新增代码保持向后兼容，旧 API 不动。

---

## 一、当前代码问题清单（需修复）

### 1.1 Bug 修复

| # | 文件 | 行 | 问题 | 修复方案 |
|---|------|-----|------|---------|
| 1 | `predictor_v3.py` | 262 | `self.prior_model` 为 None 时 `.get()` 会崩 | 加 `if self.prior_model else` 守卫（已有，确认保留） |
| 2 | `predictor_v3.py` | 454 | `load()` 恢复 priors 后没调 `_fit_prior_model()` | load() 末尾加 `if self.priors: self._fit_prior_model()` |
| 3 | `features.py` | 286 | `fuel_days_interaction` 用的是 `distance × days`，不是 PDF 要求的燃油价格交互 | 改为接入外部燃油数据（见下文），无数据时用 `distance × days / 1000` 作为 fallback |
| 4 | `features.py` | 290-297 | `prior_volatility`/`prior_weight` 只在传了 `airline_prior` 时填充，不传时缺失 | 加 else 分支填充 0.0（已修复，确认保留） |
| 5 | `price_prediction.py` | 370+ | v3 的 `predict()` 返回标量 forecast，但图表代码当列表用 | 改为从标量 base_price + `_days_to_departure_modifier()` 逐天生成曲线 |
| 6 | `predictor_v3.py` | 337-426 | Walk-Forward 没有 Purge Gap | 在 train/test 之间加 `purge_gap` 参数（默认 1 天） |

### 1.2 缺失特征（PDF 要求但未实现）

| # | PDF 章节 | 特征 | 当前状态 | 实现方式 |
|---|---------|------|---------|---------|
| 1 | §3.2 | 燃油价格滞后交互 | ❌ 假特征（distance×days） | 接入 IATA 燃油价格指数，30/90天滚动均值 × 飞行时长 |
| 2 | §4.1 | 时间分箱（清/午/晚/夜） | ❌ 未做 | 在 `extract_features()` 中加 `time_slot` 分类特征 |
| 3 | §5 | 宏观状态标识（Regime Indicators） | ❌ 未做 | 加 `regime` 特征：normal/crisis/post-crisis |
| 4 | §5 | 枢纽溢价（Hub Premium） | ❌ 未做 | 识别 hub-to-hub 航线，加 `hub_premium` 特征 |
| 5 | §6.1 | 线性基线模型 | ❌ 未做 | 加 Ridge/Lasso baseline，用于 benchmarking |
| 6 | §6.2 | 多模型 benchmarking | ❌ 未做 | 对比 RF/GBR/Ridge 的 RMSE/MAE/R² |
| 7 | §7.2 | Purge Gap | ❌ 未做 | Walk-Forward 时 train/test 之间隔离 N 天 |
| 8 | §7.2 | 目标编码折内重算 | ❌ 未做 | OOF + smoothing 在 walk-forward 内循环实现 |

---

## 二、新增/修改文件清单

```
flight_monitor/core/predictor/
├── __init__.py          — 修改：导出新增的 BaselineModel, FuelData, TimeSlotEncoder
├── features.py          — 修改：新增 time_slot, regime, hub_premium, fuel_interaction 特征
├── predictor_v3.py      — 修改：加 Purge Gap、多模型 benchmarking、线性基线
├── indian_prior.py      — 修改：提取 hub_premium 先验
├── distance.py          — 不变
├── fuel_data.py         — 新增：燃油价格数据接口（含本地缓存）
├── baseline.py          — 新增：线性基线模型（Ridge/Lasso/OLS）
└── benchmark.py         — 新增：多模型 benchmarking 工具

flight_monitor/config/
├── indian_priors.json   — 修改：追加 hub_premium 先验
└── fuel_cache.json      — 新增：燃油价格本地缓存（离线可用）

tools/
├── extract_indian_priors.py  — 修改：追加 hub_premium 提取
└── backtest_predictor.py    — 新增：端到端回测脚本
```

---

## 三、详细设计

### 3.1 `fuel_data.py` — 燃油价格数据接口

```python
"""
Flight Monitor — Aviation Fuel Price Data
===========================================

Provides jet fuel price index data with local caching.
Falls back to estimated trend when offline.

PDF Reference: §3.2 — "燃油价格的滞后效应与成本传导特征"
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict

# IATA Jet Fuel Price Index (USD per barrel, Asia-Pacific)
# Source: https://www.iata.org/en/publications/economics/fuel-monitor/
# Fallback: use estimated trend when offline

FUEL_PRICE_2024_BASELINE = 95.0  # USD per barrel (approximate 2024 average)
FUEL_PRICE_2025_BASELINE = 88.0
FUEL_PRICE_2026_BASELINE = 92.0

class FuelPriceProvider:
    """Provides jet fuel price with caching and fallback."""
    
    def __init__(self, cache_path: str = "config/fuel_cache.json"):
        self.cache_path = cache_path
        self._cache = self._load_cache()
    
    def get_fuel_price(self, date: datetime, window_days: int = 30) -> float:
        """
        Get rolling average fuel price for a date.
        
        Args:
            date: Target date
            window_days: Rolling window (30 or 90 days per PDF)
        
        Returns:
            Estimated fuel price in USD per barrel
        """
        # TODO: 接入 IATA API 或本地数据文件
        # 目前用年度基线 + 季节性波动模拟
        year = date.year
        month = date.month
        
        # Seasonal adjustment: Q1 and Q4 typically higher (heating demand)
        seasonal_factor = 1.0 + 0.05 * math.sin(2 * math.pi * (month - 1) / 12)
        
        if year <= 2024:
            return FUEL_PRICE_2024_BASELINE * seasonal_factor
        elif year <= 2025:
            return FUEL_PRICE_2025_BASELINE * seasonal_factor
        else:
            return FUEL_PRICE_2026_BASELINE * seasonal_factor
    
    def get_fuel_rolling_interaction(
        self, 
        date: datetime, 
        duration_mins: int,
        window_days: int = 30
    ) -> float:
        """
        PDF §3.2 推荐的交互特征：
        fuel_rolling_mean × flight_duration
        
        This captures cost-pass-through effect:
        - Longer flights are more sensitive to fuel price changes
        - Airlines hedge fuel, so we use rolling average (30-90 days)
        """
        fuel_price = self.get_fuel_price(date, window_days)
        # Normalize: (fuel_price / baseline) × (duration_hours)
        duration_hours = duration_mins / 60.0
        baseline = FUEL_PRICE_2026_BASELINE
        
        return (fuel_price / baseline) * duration_hours
    
    def _load_cache(self) -> Dict:
        if os.path.exists(self.cache_path):
            with open(self.cache_path, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_cache(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, 'w') as f:
            json.dump(self._cache, f, indent=2)
```

### 3.2 `baseline.py` — 线性基线模型

```python
"""
Flight Monitor — Linear Baseline Models
========================================

PDF Reference: §6.1 — "线性回归与基准模型"

Provides OLS, Ridge, Lasso baselines for benchmarking.
These serve as the "minimum viable model" — any tree ensemble
must outperform these to justify its complexity.
"""

import logging
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    import numpy as np
    from sklearn.linear_model import Ridge, Lasso, LinearRegression
    from sklearn.preprocessing import StandardScaler
    _HAS_SKLEARN = True
except ImportError:
    pass


class LinearBaseline:
    """Linear regression baseline with optional L1/L2 regularization."""
    
    def __init__(self, model_type: str = "ridge", alpha: float = 1.0):
        """
        Args:
            model_type: "ols", "ridge", or "lasso"
            alpha: Regularization strength (for ridge/lasso)
        """
        self.model_type = model_type
        self.alpha = alpha
        self.model = None
        self.scaler = StandardScaler() if _HAS_SKLEARN else None
        self._is_fitted = False
    
    def fit(self, X: List[List[float]], y: List[float]):
        """Fit linear model."""
        if not _HAS_SKLEARN:
            logger.warning("sklearn not available, baseline is mean-predictor")
            self._mean_y = sum(y) / len(y) if y else 0
            self._is_fitted = True
            return
        
        X_arr = np.array(X)
        y_arr = np.array(y)
        
        if self.model_type == "ols":
            self.model = LinearRegression()
        elif self.model_type == "ridge":
            self.model = Ridge(alpha=self.alpha)
        elif self.model_type == "lasso":
            self.model = Lasso(alpha=self.alpha)
        else:
            raise ValueError(f"Unknown model_type: {self.model_type}")
        
        X_scaled = self.scaler.fit_transform(X_arr)
        self.model.fit(X_scaled, y_arr)
        self._is_fitted = True
    
    def predict(self, X: List[List[float]]) -> List[float]:
        """Predict using fitted model."""
        if not self._is_fitted:
            return [0.0] * len(X)
        
        if not _HAS_SKLEARN:
            return [self._mean_y] * len(X)
        
        X_arr = np.array(X)
        X_scaled = self.scaler.transform(X_arr)
        return self.model.predict(X_scaled).tolist()
    
    def evaluate(self, X: List[List[float]], y: List[float]) -> Dict[str, float]:
        """Return RMSE, MAE, R²."""
        preds = self.predict(X)
        n = len(y)
        if n == 0:
            return {"rmse": 0, "mae": 0, "r2": 0}
        
        mae = sum(abs(y[i] - preds[i]) for i in range(n)) / n
        rmse = math.sqrt(sum((y[i] - preds[i]) ** 2 for i in range(n)) / n)
        ss_res = sum((y[i] - preds[i]) ** 2 for i in range(n))
        y_mean = sum(y) / n
        ss_tot = sum((yi - y_mean) ** 2 for yi in y)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        
        return {"rmse": round(rmse), "mae": round(mae), "r2": round(r2, 4)}
```

### 3.3 `benchmark.py` — 多模型 Benchmarking

```python
"""
Flight Monitor — Multi-Model Benchmarking
==========================================

PDF Reference: §6 — "算法架构评估"

Compares multiple models on the same walk-forward splits:
- Linear Baseline (Ridge)
- Random Forest
- Gradient Boosting (current)

Reports RMSE, MAE, R² for each.
"""

import logging
from typing import List, Dict, Tuple
from .baseline import LinearBaseline
from .predictor_v3 import PricePredictorV3

logger = logging.getLogger(__name__)


class ModelBenchmark:
    """Benchmark multiple models on walk-forward splits."""
    
    def __init__(self):
        self.results = {}
    
    def run(
        self,
        X: List[List[float]],
        y: List[float],
        feature_names: List[str],
        n_splits: int = 5,
        min_train_size: int = 20,
        purge_gap: int = 1,
    ) -> Dict:
        """
        Run walk-forward benchmark across all models.
        
        Args:
            X: Feature vectors
            y: Target prices
            feature_names: Names for feature columns
            n_splits: Number of walk-forward folds
            min_train_size: Minimum training samples
            purge_gap: Days to exclude between train/test (PDF §7.2)
        
        Returns:
            Dict with per-model metrics
        """
        # TODO: 实现 walk-forward benchmark
        # 1. 按时间切分 X, y
        # 2. 每个 fold 训练 Ridge, RF, GBR
        # 3. 在 test 集上计算 RMSE/MAE/R²
        # 4. 汇总对比
        pass
```

### 3.4 `features.py` — 新增特征

在 `extract_features()` 中新增以下特征：

```python
# ── 11. Time slot binning (PDF §4.1) ──
# 将起飞时间分为 4 个时段，提升可解释性
dep_hour = _parse_hour(latest.get("departure_time", ""))
if dep_hour is not None:
    if 6 <= dep_hour < 12:
        features["time_slot"] = 0  # morning
    elif 12 <= dep_hour < 18:
        features["time_slot"] = 1  # afternoon
    elif 18 <= dep_hour < 22:
        features["time_slot"] = 2  # evening
    else:
        features["time_slot"] = 3  # redeye
else:
    features["time_slot"] = -1  # unknown

# ── 12. Regime indicator (PDF §5) ──
# 宏观状态：normal=0, crisis=1, post_crisis=2
# 目前用年份硬编码，后续可接入外部数据
dep_year = dep_date.year if dep_date else 2026
if dep_year <= 2020:
    features["regime"] = 1  # COVID
elif dep_year <= 2022:
    features["regime"] = 2  # post-COVID recovery
else:
    features["regime"] = 0  # normal

# ── 13. Hub premium (PDF §5) ──
# 识别枢纽对枢纽航线（如 北京-上海、北京-广州）
HUB_CITIES = {"北京", "上海", "广州", "深圳", "成都"}
features["hub_premium"] = 1.0 if (departure_city in HUB_CITIES and destination_city in HUB_CITIES) else 0.0

# ── 14. Fuel interaction (PDF §3.2) ──
# 替换原来的假特征
fuel_provider = FuelPriceProvider()
duration_mins = _parse_duration_minutes(latest.get("duration", ""))
features["fuel_interaction"] = fuel_provider.get_fuel_rolling_interaction(
    dep_date, duration_mins, window_days=30
)
features["fuel_interaction_90d"] = fuel_provider.get_fuel_rolling_interaction(
    dep_date, duration_mins, window_days=90
)
```

### 3.5 `predictor_v3.py` — 新增 Purge Gap

```python
def backtest_walk_forward(
    self,
    records: List[Dict],
    departure_city: str,
    destination_city: str,
    holidays: List = None,
    n_splits: int = 5,
    min_train_size: int = 10,
    purge_gap: int = 1,  # 新增：PDF §7.2 要求
) -> Dict:
    """Run walk-forward backtest with Purge Gap."""
    
    # ... 现有代码 ...
    
    for fold_i in range(n_splits):
        split_point = min_train_size + fold_i * fold_size
        if split_point >= len(sorted_records):
            break
        
        train_data = sorted_records[:split_point]
        # 关键修改：加 Purge Gap
        test_start = min(split_point + purge_gap, len(sorted_records))
        test_data = sorted_records[test_start:min(test_start + fold_size, len(sorted_records))]
        
        # ... 其余逻辑不变 ...
```

### 3.6 `indian_prior.py` — 追加 Hub Premium 先验

```python
def _extract_hub_premium(self, records: List[Dict]) -> Dict:
    """
    PDF §5: Hub-to-hub routes have a "Hub Premium" — base fares
    significantly higher than regular routes.
    
    We compute this as the ratio of hub-route median to overall median.
    """
    HUB_AIRPORTS = {"Delhi", "Mumbai", "Bangalore", "Kolkata", "Chennai"}
    
    hub_prices = []
    non_hub_prices = []
    
    for r in records:
        src = r.get("source", "")
        dst = r.get("destination", "")
        price = r.get("price", 0)
        if price <= 0:
            continue
        
        if src in HUB_AIRPORTS and dst in HUB_AIRPORTS:
            hub_prices.append(price)
        else:
            non_hub_prices.append(price)
    
    if hub_prices and non_hub_prices:
        hub_median = statistics.median(hub_prices)
        non_hub_median = statistics.median(non_hub_prices)
        premium_ratio = hub_median / non_hub_median if non_hub_median > 0 else 1.0
    else:
        premium_ratio = 1.0
    
    return {
        "hub_premium_ratio": round(premium_ratio, 3),
        "hub_median": statistics.median(hub_prices) if hub_prices else 0,
        "non_hub_median": statistics.median(non_hub_prices) if non_hub_prices else 0,
    }
```

---

## 四、数据流（更新后）

```
携程 m.ctrip.com → Playwright → getLowestPriceCalendar → 91 条日历数据
    ↓
去重为 N 个唯一航班
    ↓
FlightAggregator → N 航班 × 7 平台比价 = M 个价格
    ↓
price_prediction.py → generate_prediction_chart()
    ↓
predictor_v3.py → PricePredictorV3.predict()
    ↓
features.py → extract_features() → 36 维特征向量
    ↓
┌─────────────────────────────────────────────┐
│  Cold Start (<5 records):                   │
│    Indian Prior Model (behavioral patterns) │
│    + Hub Premium + Time Slot + Regime       │
│                                             │
│  Warm (5-30 records):                       │
│    Bayesian Blending (prior + online GBR)   │
│                                             │
│  Hot (>30 records):                         │
│    sklearn GradientBoosting (primary)       │
│    + Ridge baseline (benchmarking)          │
│    + Walk-Forward Validation (with gap)     │
└─────────────────────────────────────────────┘
    ↓
返回 forecast + lower_ci + upper_ci + model_name
```

---

## 五、实现优先级

| 优先级 | 任务 | 工作量 | 说明 |
|--------|------|--------|------|
| **P0** | Bug 修复 (#1-#5) | 小 | 现有代码必须修，否则运行时会崩 |
| **P0** | Purge Gap | 小 | PDF 明确要求，几行代码 |
| **P1** | 时间分箱特征 | 小 | 加 1 个特征 |
| **P1** | Regime Indicator | 小 | 加 1 个特征 |
| **P1** | Hub Premium 特征 | 小 | 加 1 个特征 + 从印度数据提取先验 |
| **P1** | 燃油价格交互特征 | 中 | 新建 `fuel_data.py`，接入外部数据或本地缓存 |
| **P2** | 线性基线模型 | 中 | 新建 `baseline.py` |
| **P2** | 多模型 Benchmarking | 中 | 新建 `benchmark.py` |
| **P3** | 目标编码 OOF+Smoothing | 大 | 需要重构 walk-forward 内循环 |

---

## 六、测试要求

每个新模块必须有对应的单元测试：

```
tests/
├── test_fuel_data.py        — FuelPriceProvider 缓存、fallback、交互特征
├── test_baseline.py         — LinearBaseline fit/predict/evaluate
├── test_benchmark.py        — ModelBenchmark walk-forward 对比
├── test_features_v3.py      — 新增特征的正确性（time_slot, regime, hub_premium）
├── test_predictor_v3_purge.py — Purge Gap 正确性
└── test_indian_prior_hub.py — Hub Premium 先验提取
```

---

## 七、注意事项

1. **向后兼容**：`price_prediction.py` 的 `generate_prediction_chart()` 签名不能变
2. **sklearn 依赖**：所有 sklearn 调用都要在 `has_sklearn` 守卫内，无 sklearn 时 graceful fallback
3. **燃油数据**：目前用年度基线 + 季节性波动模拟，后续接入 IATA API 时只需改 `fuel_data.py`
4. **Hub 城市**：`HUB_CITIES` 集合需要根据实际航线数据调整
5. **Regime 标识**：目前用年份硬编码，后续可接入外部事件数据
