# -*- coding: utf-8 -*-
"""
过拟合修复方案 — 降低模型复杂度 + 时间序列友好验证

修复策略:
1. 减少特征维度 (20 → 8 核心特征)
2. 降低 GBR 复杂度 (max_depth=3→2, n_estimators=50→20)
3. 增加 RFR 正则化 (max_depth=5→3, 添加 min_samples_leaf)
4. 时间序列分割 (不打乱时序)
5. 增加 Ridge 正则化强度 (alpha=1.0→5.0)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from flight_monitor.core.ml_predictor import (
    EnsemblePredictor, build_training_data,
    _rmse, _r2_score, _mae, _HAS_SKLEARN,
)
from flight_monitor.core.database import Database
from flight_monitor.core.price_prediction import get_historical_prices


# 核心特征子集 (8个最稳定、最重要的特征)
CORE_FEATURES = [
    0,   # current_price
    3,   # volatility
    4,   # trend_7d
    5,   # trend_30d
    6,   # days_left_ratio
    7,   # log_days_left
    10,  # month_ratio
    13,  # data_density
]


def select_feature_subset(X, feature_indices):
    """从完整特征矩阵中选择子集"""
    return [[row[i] for i in feature_indices] for row in X]


def fixed_ensemble_train(X, y):
    """修复后的训练流程 — 降低复杂度 + 时间序列友好"""
    n = len(X)
    split = max(1, int(n * 0.8))
    X_tr, y_tr = X[:split], y[:split]
    X_val, y_val = X[split:], y[split:]

    # 降低复杂度的模型配置
    if _HAS_SKLEARN:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.linear_model import Ridge
        import numpy as np

        models = [
            ("GBR", GradientBoostingRegressor(
                n_estimators=20,      # 50→20
                max_depth=2,          # 3→2
                subsample=0.8,
                learning_rate=0.05,   # 0.1→0.05
                min_samples_leaf=5,   # 新增
                random_state=42,
            )),
            ("RFR", RandomForestRegressor(
                n_estimators=20,      # 50→20
                max_depth=3,          # 5→3
                min_samples_leaf=5,   # 新增
                max_features='sqrt',  # 新增
                random_state=42,
                n_jobs=-1,
            )),
            ("Ridge", Ridge(alpha=5.0)),  # 1.0→5.0
        ]

        metrics = {}
        weights = []
        for name, model in models:
            model.fit(np.array(X_tr), np.array(y_tr))
            yp_val = model.predict(np.array(X_val))
            yp_tr = model.predict(np.array(X_tr))
            rmse_val = _rmse(y_val, list(yp_val))
            rmse_tr = _rmse(y_tr, list(yp_tr))
            r2_val = _r2_score(y_val, list(yp_val))
            r2_tr = _r2_score(y_tr, list(yp_tr))
            metrics[name] = {
                "rmse_train": rmse_tr, "rmse_val": rmse_val,
                "r2_train": r2_tr, "r2_val": r2_val,
                "rmse_ratio": rmse_val / max(rmse_tr, 1),
                "r2_gap": r2_tr - r2_val,
            }
            weights.append(1.0 / max(rmse_val, 1))

        # 归一化权重
        w_sum = sum(weights)
        weights = [w / w_sum for w in weights]

        return models, metrics, weights

    else:
        # Pure-Python fallback (already conservative)
        from flight_monitor.core.ml_predictor import (
            _GradientBoostingRegressor, _BaggedStumps, _RidgeLinear
        )
        models = [
            ("GBR", _GradientBoostingRegressor(n_estimators=20, learning_rate=0.05)),
            ("RFR", _BaggedStumps(n_estimators=15, max_features=3)),
            ("Ridge", _RidgeLinear(alpha=5.0)),
        ]
        metrics = {}
        weights = []
        for name, model in models:
            model.fit(X_tr, y_tr)
            yp_val = model.predict(X_val)
            yp_tr = model.predict(X_tr)
            rmse_val = _rmse(y_val, yp_val)
            rmse_tr = _rmse(y_tr, yp_tr)
            r2_val = _r2_score(y_val, yp_val)
            r2_tr = _r2_score(y_tr, yp_tr)
            metrics[name] = {
                "rmse_train": rmse_tr, "rmse_val": rmse_val,
                "r2_train": r2_tr, "r2_val": r2_val,
                "rmse_ratio": rmse_val / max(rmse_tr, 1),
                "r2_gap": r2_tr - r2_val,
            }
            weights.append(1.0 / max(rmse_val, 1))
        w_sum = sum(weights)
        weights = [w / w_sum for w in weights]
        return models, metrics, weights


def main():
    print("=" * 60)
    print("Overfitting Fix Validation")
    print("=" * 60)

    # Load data
    db = Database("flight_monitor/flight_monitor.db")
    conn = db._get_conn()
    row = conn.execute('''
        SELECT q.id, COUNT(pr.id) as cnt
        FROM search_queries q
        JOIN price_records pr ON q.id = pr.query_id AND pr.is_mock = 0
        WHERE q.departure LIKE '%北京%' AND q.destination LIKE '%上海%'
        GROUP BY q.id ORDER BY cnt DESC LIMIT 1
    ''').fetchone()
    if not row:
        print("[FAIL] No data")
        return
    query_id = row["id"]

    records = get_historical_prices(db, query_id, days_back=30, real_only=False, include_mock=False)
    print(f"Data: {len(records)} price points")

    # Build training data
    X_full, y = build_training_data(records, "北京", "上海")
    print(f"Training samples: {len(X_full)}, Full features: {len(X_full[0])}")

    # === Test 1: Original (20 features, default complexity) ===
    print(f"\n{'='*60}")
    print("Test 1: ORIGINAL (20 features, default complexity)")
    print(f"{'='*60}")
    models_orig, metrics_orig, weights_orig = fixed_ensemble_train(X_full, y)
    # Actually use original EnsemblePredictor for comparison
    ensemble_orig = EnsemblePredictor(n_estimators=50)
    report_orig = ensemble_orig.train(X_full, y, val_frac=0.2)
    for name, m in report_orig["metrics"].items():
        r2_key = 'R2' if 'R2' in m else 'R²'
        print(f"  {name}: Val RMSE={m['RMSE']:.1f}, Val R2={m[r2_key]:+.3f}")

    # === Test 2: Reduced features (8 core features) ===
    print(f"\n{'='*60}")
    print("Test 2: REDUCED FEATURES (8 core features)")
    print(f"{'='*60}")
    X_reduced = select_feature_subset(X_full, CORE_FEATURES)
    print(f"Features: {len(X_reduced[0])}")
    ensemble_red = EnsemblePredictor(n_estimators=50)
    report_red = ensemble_red.train(X_reduced, y, val_frac=0.2)
    for name, m in report_red["metrics"].items():
        r2_key = 'R2' if 'R2' in m else 'R²'
        print(f"  {name}: Val RMSE={m['RMSE']:.1f}, Val R2={m[r2_key]:+.3f}")

    # === Test 3: Reduced features + lower complexity ===
    print(f"\n{'='*60}")
    print("Test 3: REDUCED FEATURES + LOWER COMPLEXITY (FIXED)")
    print(f"{'='*60}")
    models_fix, metrics_fix, weights_fix = fixed_ensemble_train(X_reduced, y)
    for name, m in metrics_fix.items():
        level = "[OK]" if m["rmse_ratio"] < 1.5 else "[!]" if m["rmse_ratio"] < 2.0 else "[!!]"
        print(f"  {level} {name}: Train RMSE={m['rmse_train']:.1f}, Val RMSE={m['rmse_val']:.1f}, "
              f"Ratio={m['rmse_ratio']:.2f}, R2 gap={m['r2_gap']:+.3f}")

    # === Summary ===
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Original (20 feat, complex):  GBR R2={report_orig['metrics']['GBR'].get('R2', report_orig['metrics']['GBR'].get('R²', 0)):+.3f}")
    print(f"Reduced   (8 feat, complex):  GBR R2={report_red['metrics']['GBR'].get('R2', report_red['metrics']['GBR'].get('R²', 0)):+.3f}")
    gbr_fix_r2 = metrics_fix['GBR']['r2_val']
    print(f"Fixed     (8 feat, simple):   GBR R2={gbr_fix_r2:+.3f}")
    print(f"\nRecommendation: Use 8 core features + reduced complexity")


if __name__ == "__main__":
    main()
