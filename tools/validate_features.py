"""
Feature Engineering Validation Script
=====================================
Runs training with new features and prints feature importance.
Uses project venv.
"""
import sys
import os
import statistics

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from core.database import Database
from core.predictor.predictor_v3 import PricePredictorV3
from core.predictor.features import _get_feature_names

DB_PATH = os.path.join(_PROJECT_ROOT, "flight_monitor.db")


def main():
    db = Database(DB_PATH)

    # Get all queries with data
    queries = db.get_all_queries()
    if not queries:
        print("No queries found in DB.")
        db.close()
        return

    predictor = PricePredictorV3()

    # Collect training data from all routes
    all_X, all_y = [], []
    route_results = []

    for q in queries:
        # Get real (non-mock) individual price records for ML
        records = db.get_real_prices_for_ml(q.id, limit=200)
        if len(records) < 15:
            # Fall back to all records
            records_all = db._get_conn().execute(
                "SELECT price, recorded_at as date, sub_class, seat_inventory, "
                "departure_time, stops, is_mock "
                "FROM price_records WHERE query_id=? "
                "ORDER BY recorded_at ASC LIMIT 200",
                (q.id,)
            ).fetchall()
            records = [dict(r) for r in records_all]

        if len(records) < 15:
            continue

        dep = q.departure
        dst = q.destination
        dep_date = q.departure_date or ""

        # Walk-forward backtest
        bt_result = predictor.backtest_walk_forward(
            records=records,
            departure_city=dep,
            destination_city=dst,
            departure_date=dep_date,
            n_splits=3,
            min_train_size=8,
            purge_gap=1,
        )

        if "error" not in bt_result:
            route_results.append((
                f"{dep}->{dst}",
                bt_result["r2"],
                bt_result["rmse"],
                bt_result["mape"],
                bt_result["n_predictions"],
            ))

        # Build training data
        X, y = predictor.build_training_data(records, dep, dst, departure_date=dep_date)
        all_X.extend(X)
        all_y.extend(y)

    # Print per-route results
    print(f"\n{'='*65}")
    print(f" Per-Route Walk-Forward Backtest Results ({len(route_results)} routes)")
    print(f"{'='*65}")
    print(f"{'Route':<25} {'R²':>8} {'RMSE':>8} {'MAPE%':>8} {'N_pred':>8}")
    print("-" * 65)
    for label, r2, rmse, mape, n_pred in route_results:
        print(f"{label:<25} {r2:>8.3f} {rmse:>8.0f} {mape:>8.1f} {n_pred:>8}")

    if route_results:
        avg_r2 = statistics.mean(r[1] for r in route_results)
        avg_rmse = statistics.mean(r[2] for r in route_results)
        avg_mape = statistics.mean(r[3] for r in route_results)
        print("-" * 65)
        print(f"{'AVERAGE':<25} {avg_r2:>8.3f} {avg_rmse:>8.0f} {avg_mape:>8.1f}")

    # Feature importance via Ridge on all data combined
    print(f"\n{'='*65}")
    print(" Training Ridge on aggregated data to inspect feature importance")
    print(f"{'='*65}")

    if len(all_X) < 10:
        print(f"Not enough training samples ({len(all_X)}), skip feature importance.")
        db.close()
        return

    print(f"Total training samples: {len(all_X)}")
    print(f"Feature count: {len(_get_feature_names())}")

    feature_names = _get_feature_names()
    X_mat = [[x.get(name, 0.0) for name in feature_names] for x in all_X]

    import numpy as np
    from sklearn.linear_model import Ridge

    model = Ridge(alpha=1.0)
    model.fit(np.array(X_mat), np.array(all_y))

    # Predictions for sanity check
    preds = model.predict(X_mat)
    ss_res = sum((all_y[i] - preds[i]) ** 2 for i in range(len(all_y)))
    ss_tot = sum((y - statistics.mean(all_y)) ** 2 for y in all_y)
    r2 = 1 - ss_res / max(ss_tot, 1e-10)
    rmse = (ss_res / len(all_y)) ** 0.5

    print(f"\nRidge model (for importance inspection): R²={r2:.3f}, RMSE={rmse:.0f}")

    # Feature importance (absolute coefficient × std)
    coef_importance = []
    for i, name in enumerate(feature_names):
        col = [row[i] for row in X_mat]
        col_std = statistics.stdev(col) if len(col) > 1 else 1.0
        importance = abs(model.coef_[i]) * col_std
        coef_importance.append((name, model.coef_[i], importance))

    coef_importance.sort(key=lambda x: -x[2])

    print(f"\n{'Feature':<35} {'Coef':>10} {'|Coef|*Std':>10}")
    print("-" * 57)
    for name, coef, imp in coef_importance:
        print(f"{name:<35} {coef:>10.4f} {imp:>10.4f}")

    # Show sample feature values
    print(f"\n{'='*65}")
    print(" Sample feature values (first 3 training examples)")
    print("=" * 65)
    for idx in range(min(3, len(all_X))):
        x = all_X[idx]
        print(f"\n--- Sample {idx+1} (y={all_y[idx]:.0f}) ---")
        for name in _get_feature_names():
            if name in x:
                print(f"  {name:<35} {x[name]:.4f}")

    db.close()


if __name__ == "__main__":
    main()
