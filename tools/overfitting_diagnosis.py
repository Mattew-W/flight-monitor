# -*- coding: utf-8 -*-
"""
Overfitting Diagnosis Tool for EnsemblePredictor
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

import math
import random
import statistics
from typing import List, Dict, Tuple

from flight_monitor.core.ml_predictor import (
    EnsemblePredictor, build_training_data, extract_features,
    _rmse, _r2_score, _mae, FEATURE_NAMES, _HAS_SKLEARN,
)
from flight_monitor.core.database import Database
from flight_monitor.core.price_prediction import get_historical_prices


def load_real_data(db_path: str = "flight_monitor/flight_monitor.db") -> List[Dict]:
    db = Database(db_path)
    conn = db._get_conn()
    # Find the query with the most real data for BJS->SHA
    row = conn.execute('''
        SELECT q.id, q.departure, q.destination, COUNT(pr.id) as cnt
        FROM search_queries q
        JOIN price_records pr ON q.id = pr.query_id AND pr.is_mock = 0
        WHERE q.departure LIKE '%北京%' AND q.destination LIKE '%上海%'
        GROUP BY q.id
        ORDER BY cnt DESC
        LIMIT 1
    ''').fetchone()
    if not row:
        # Fallback: any query with real data
        row = conn.execute('''
            SELECT q.id, q.departure, q.destination, COUNT(pr.id) as cnt
            FROM search_queries q
            JOIN price_records pr ON q.id = pr.query_id AND pr.is_mock = 0
            GROUP BY q.id
            ORDER BY cnt DESC
            LIMIT 1
        ''').fetchone()
    if not row or row["cnt"] < 7:
        print("[FAIL] No query with sufficient real data")
        return []
    query_id = row["id"]
    print(f"  Route: {row['departure']} -> {row['destination']} (qid={query_id}, {row['cnt']} real records)")
    records = get_historical_prices(db, query_id, days_back=30, real_only=False, include_mock=False)
    print(f"  Historical price points (deduplicated): {len(records)}")
    return records


def diagnose_train_val_gap(X, y, val_frac=0.2) -> Dict:
    n = len(X)
    split = max(1, int(n * (1 - val_frac)))
    X_tr, y_tr = X[:split], y[:split]
    X_val, y_val = X[split:], y[split:]
    print(f"\n{'='*60}")
    print(f"Diag 1: Train vs Validation Gap")
    print(f"{'='*60}")
    print(f"  Train: {len(X_tr)} | Val: {len(X_val)} | Features: {len(X[0])}")
    print(f"  Sample/Feature ratio: {len(X_tr)/len(X[0]):.1f}")
    ensemble = EnsemblePredictor(n_estimators=20)
    ensemble.train(X_tr, y_tr, val_frac=0)
    results = {}
    for name, model in zip(ensemble.metrics.keys(), ensemble.models):
        # Apply same feature selection as training
        from flight_monitor.core.ml_predictor import select_features
        X_tr_sel = select_features(X_tr) if ensemble._feature_indices else X_tr
        X_val_sel = select_features(X_val) if ensemble._feature_indices else X_val
        yp_tr = model.predict(X_tr_sel)
        rmse_tr = _rmse(y_tr, yp_tr)
        r2_tr = _r2_score(y_tr, yp_tr)
        mae_tr = _mae(y_tr, yp_tr)
        yp_val = model.predict(X_val_sel)
        rmse_val = _rmse(y_val, yp_val)
        r2_val = _r2_score(y_val, yp_val)
        mae_val = _mae(y_val, yp_val)
        rmse_ratio = rmse_val / max(rmse_tr, 1)
        r2_gap = r2_tr - r2_val
        results[name] = {"rmse_train": rmse_tr, "rmse_val": rmse_val, "rmse_ratio": rmse_ratio,
                         "r2_train": r2_tr, "r2_val": r2_val, "r2_gap": r2_gap,
                         "mae_train": mae_tr, "mae_val": mae_val}
        level = "[OK] Normal"
        if rmse_ratio > 2.0 or r2_gap > 0.3:
            level = "[!!] SEVERE overfit"
        elif rmse_ratio > 1.5 or r2_gap > 0.15:
            level = "[!] Mild overfit"
        elif rmse_ratio > 1.2:
            level = "[~] Slight variance"
        print(f"\n  [{name}] {level}")
        print(f"    Train -- RMSE={rmse_tr:.1f}, R2={r2_tr:+.3f}, MAE={mae_tr:.1f}")
        print(f"    Val   -- RMSE={rmse_val:.1f}, R2={r2_val:+.3f}, MAE={mae_val:.1f}")
        print(f"    RMSE ratio(V/T)={rmse_ratio:.2f}, R2 gap={r2_gap:+.3f}")
    return results


def diagnose_learning_curve(X, y, n_points=8) -> Dict:
    n = len(X)
    step = max(1, (n - 2) // n_points)
    sizes = list(range(max(5, step), n, step))
    if sizes and sizes[-1] != n:
        sizes.append(n)
    print(f"\n{'='*60}")
    print(f"Diag 2: Learning Curve")
    print(f"{'='*60}")
    results = {"sizes": [], "train_rmse": [], "val_rmse": [], "train_r2": [], "val_r2": []}
    for size in sizes:
        split = max(1, int(size * 0.8))
        X_tr = X[:split]; y_tr = y[:split]
        X_val = X[split:size]; y_val = y[split:size]
        if len(X_val) < 2:
            continue
        ensemble = EnsemblePredictor(n_estimators=20)
        ensemble.train(X_tr, y_tr, val_frac=0)
        model = ensemble.models[0]
        from flight_monitor.core.ml_predictor import select_features
        X_tr_sel = select_features(X_tr) if ensemble._feature_indices else X_tr
        X_val_sel = select_features(X_val) if ensemble._feature_indices else X_val
        yp_tr = model.predict(X_tr_sel)
        yp_val = model.predict(X_val_sel)
        rmse_tr = _rmse(y_tr, yp_tr)
        rmse_val = _rmse(y_val, yp_val)
        r2_tr = _r2_score(y_tr, yp_tr)
        r2_val = _r2_score(y_val, yp_val)
        results["sizes"].append(size)
        results["train_rmse"].append(rmse_tr)
        results["val_rmse"].append(rmse_val)
        results["train_r2"].append(r2_tr)
        results["val_r2"].append(r2_val)
        gap = rmse_val - rmse_tr
        print(f"  n={size:3d} | Train RMSE={rmse_tr:7.1f} R2={r2_tr:+.3f} | Val RMSE={rmse_val:7.1f} R2={r2_val:+.3f} | Gap={gap:+.1f}")
    if len(results["sizes"]) >= 3:
        early_gap = results["val_rmse"][1] - results["train_rmse"][1]
        late_gap = results["val_rmse"][-1] - results["train_rmse"][-1]
        if late_gap > early_gap * 1.5:
            print(f"\n  [WARN] Gap widens with more data ({early_gap:.1f} -> {late_gap:.1f}) -> model too complex")
        elif late_gap < early_gap * 0.8:
            print(f"\n  [OK] Gap narrows with more data ({early_gap:.1f} -> {late_gap:.1f}) -> more data helps")
        else:
            print(f"\n  [INFO] Gap stable ({early_gap:.1f} -> {late_gap:.1f})")
    return results


def diagnose_kfold_cv(X, y, k=5) -> Dict:
    n = len(X)
    fold_size = n // k
    print(f"\n{'='*60}")
    print(f"Diag 3: {k}-Fold Cross-Validation Stability")
    print(f"{'='*60}")
    fold_rmses = []
    fold_r2s = []
    for i in range(k):
        val_start = i * fold_size
        val_end = val_start + fold_size if i < k - 1 else n
        X_val = X[val_start:val_end]
        y_val = y[val_start:val_end]
        X_tr = X[:val_start] + X[val_end:]
        y_tr = y[:val_start] + y[val_end:]
        if len(X_tr) < 5 or len(X_val) < 2:
            continue
        ensemble = EnsemblePredictor(n_estimators=20)
        ensemble.train(X_tr, y_tr, val_frac=0)
        model = ensemble.models[0]
        from flight_monitor.core.ml_predictor import select_features
        X_val_sel = select_features(X_val) if ensemble._feature_indices else X_val
        yp_val = model.predict(X_val_sel)
        rmse_val = _rmse(y_val, yp_val)
        r2_val = _r2_score(y_val, yp_val)
        fold_rmses.append(rmse_val)
        fold_r2s.append(r2_val)
        print(f"  Fold {i+1}: Train={len(X_tr):3d} | Val={len(X_val):3d} | RMSE={rmse_val:.1f} | R2={r2_val:+.3f}")
    if fold_rmses:
        mean_rmse = statistics.mean(fold_rmses)
        std_rmse = statistics.stdev(fold_rmses) if len(fold_rmses) > 1 else 0
        mean_r2 = statistics.mean(fold_r2s)
        std_r2 = statistics.stdev(fold_r2s) if len(fold_r2s) > 1 else 0
        cv_ratio = std_rmse / max(mean_rmse, 1)
        stability = "[OK] Stable"
        if cv_ratio > 0.3:
            stability = "[!!] Unstable (high variance)"
        elif cv_ratio > 0.15:
            stability = "[!] Moderate variance"
        print(f"\n  Summary: RMSE = {mean_rmse:.1f} +/- {std_rmse:.1f} (CV={cv_ratio:.2f})")
        print(f"           R2   = {mean_r2:+.3f} +/- {std_r2:.3f}")
        print(f"  Stability: {stability}")
        return {"mean_rmse": mean_rmse, "std_rmse": std_rmse, "cv_ratio": cv_ratio,
                "mean_r2": mean_r2, "std_r2": std_r2}
    return {}


def diagnose_feature_importance_stability(X, y, n_runs=5) -> Dict:
    print(f"\n{'='*60}")
    print(f"Diag 4: Feature Importance Stability ({n_runs} runs)")
    print(f"{'='*60}")
    all_importances = []
    for run in range(n_runs):
        combined = list(zip(X, y))
        random.shuffle(combined)
        X_shuf, y_shuf = zip(*combined)
        X_shuf, y_shuf = list(X_shuf), list(y_shuf)
        ensemble = EnsemblePredictor(n_estimators=20)
        ensemble.train(X_shuf, y_shuf, val_frac=0.2)
        if ensemble.feature_importance:
            all_importances.append(ensemble.feature_importance)
            top5 = sorted(ensemble.feature_importance.items(), key=lambda x: -x[1])[:5]
            top5_str = ", ".join(f"{k}={v:.2f}" for k, v in top5)
            print(f"  Run {run+1}: {top5_str}")
    if not all_importances:
        return {}
    feature_vars = {}
    for feat in FEATURE_NAMES[:len(X[0])]:
        vals = [imp.get(feat, 0) for imp in all_importances]
        if vals:
            feature_vars[feat] = {"mean": statistics.mean(vals),
                                   "std": statistics.stdev(vals) if len(vals) > 1 else 0}
    print(f"\n  Feature importance variance:")
    for feat, stats in sorted(feature_vars.items(), key=lambda x: -x[1]["mean"])[:8]:
        cv = stats["std"] / max(stats["mean"], 0.01)
        stable = "[OK]" if cv < 0.5 else "[WARN]"
        print(f"    {stable} {feat:20s}: mean={stats['mean']:.3f}, std={stats['std']:.3f}, CV={cv:.2f}")
    return feature_vars


def diagnose_model_complexity(X, y) -> Dict:
    print(f"\n{'='*60}")
    print(f"Diag 5: Model Complexity vs Data")
    print(f"{'='*60}")
    n = len(X)
    d = len(X[0])
    ratio = n / d
    print(f"  Samples: {n} | Features: {d} | Ratio: {ratio:.1f}")
    if ratio < 5:
        risk = "[!!] HIGH - samples severely insufficient"
    elif ratio < 10:
        risk = "[!] MEDIUM - samples low"
    elif ratio < 20:
        risk = "[~] Acceptable"
    else:
        risk = "[OK] Sufficient"
    print(f"  Complexity risk: {risk}")
    print(f"\n  GBR: n_estimators=50, max_depth=3 (sklearn) / stumps (pure-Python)")
    print(f"       subsample=0.8 -> regularization")
    print(f"  RFR: n_estimators=50, max_depth=5")
    print(f"  Ridge: alpha=1.0 -> L2 regularization")
    ensemble = EnsemblePredictor(n_estimators=20)
    ensemble.train(X, y, val_frac=0.2)
    print(f"\n  Ensemble weights (inverse val RMSE):")
    for i, (name, metrics) in enumerate(ensemble.metrics.items()):
        w = ensemble.weights[i] if i < len(ensemble.weights) else 0
        r2_key = 'R2' if 'R2' in metrics else 'R²'
        print(f"    {name}: weight={w:.3f}, Val RMSE={metrics['RMSE']:.1f}, Val R2={metrics[r2_key]:+.3f}")
    if ensemble.weights:
        max_w = max(ensemble.weights)
        if max_w > 0.7:
            print(f"\n  [WARN] Weight too concentrated (max={max_w:.2f}) -> ensemble degraded")
        else:
            print(f"\n  [OK] Weight distribution healthy (max={max_w:.2f})")
    return {"n_samples": n, "n_features": d, "ratio": ratio}


def generate_report(all_results: Dict):
    print(f"\n{'='*60}")
    print(f"FINAL REPORT")
    print(f"{'='*60}")
    issues = []
    suggestions = []
    if "train_val" in all_results:
        for name, metrics in all_results["train_val"].items():
            if metrics["rmse_ratio"] > 1.5:
                issues.append(f"{name}: RMSE ratio={metrics['rmse_ratio']:.2f} (Val/Train)")
                suggestions.append(f"Reduce {name} complexity (lower n_estimators or max_depth)")
            if metrics["r2_gap"] > 0.2:
                issues.append(f"{name}: R2 gap={metrics['r2_gap']:.3f}")
    if "kfold" in all_results and all_results["kfold"]:
        cv = all_results["kfold"].get("cv_ratio", 0)
        if cv > 0.2:
            issues.append(f"CV coefficient={cv:.2f} (unstable)")
            suggestions.append("More data or simpler model")
    if "complexity" in all_results:
        ratio = all_results["complexity"].get("ratio", 0)
        if ratio < 10:
            issues.append(f"Sample/feature ratio={ratio:.1f} (low)")
            suggestions.append("Reduce features or add data")
    if issues:
        print(f"\n[WARN] {len(issues)} overfitting risk(s) found:")
        for issue in issues:
            print(f"  - {issue}")
        print(f"\n[SUGGESTION]:")
        for sug in suggestions:
            print(f"  - {sug}")
    else:
        print(f"\n[OK] No significant overfitting detected")


def main():
    print("=" * 60)
    print("Flight Price Prediction - Overfitting Diagnosis")
    print("=" * 60)
    print(f"sklearn available: {_HAS_SKLEARN}")
    records = load_real_data()
    if not records or len(records) < 7:
        print("[FAIL] Insufficient data")
        return
    departure = "北京"
    destination = "上海"
    X, y = build_training_data(records, departure, destination)
    if not X or len(X) < 7:
        print(f"[FAIL] Insufficient training samples: {len(X) if X else 0}")
        return
    print(f"  Training samples: {len(X)}, Features: {len(X[0])}")
    all_results = {}
    all_results["train_val"] = diagnose_train_val_gap(X, y)
    all_results["learning_curve"] = diagnose_learning_curve(X, y)
    all_results["kfold"] = diagnose_kfold_cv(X, y, k=5)
    all_results["feature_stability"] = diagnose_feature_importance_stability(X, y, n_runs=5)
    all_results["complexity"] = diagnose_model_complexity(X, y)
    generate_report(all_results)


if __name__ == "__main__":
    main()
