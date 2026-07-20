"""Quick lightweight feature validation — runs on 5 routes, uses smaller Ridge."""
import sys, os, statistics, math
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from core.database import Database
from core.predictor.features import extract_features, _get_feature_names

DB_PATH = os.path.join(_PROJECT_ROOT, "flight_monitor.db")

def main():
    db = Database(DB_PATH)
    queries = db.get_all_queries()[:5]
    if not queries:
        print("No queries."); db.close(); return

    feature_names = _get_feature_names()
    print(f"Feature count: {len(feature_names)}")
    print(f"New features: price_change_1d, price_change_3d, rolling_mean_3d, rolling_std_3d, "
          f"days_until_departure_sq, is_weekend, is_holiday_period, price_momentum")
    print()

    all_X, all_y = [], []
    for q in queries:
        records = db._get_conn().execute(
            "SELECT price, recorded_at as date, sub_class, seat_inventory, "
            "departure_time, stops, is_mock "
            "FROM price_records WHERE query_id=? "
            "ORDER BY recorded_at ASC LIMIT 200",
            (q.id,)
        ).fetchall()
        records = [dict(r) for r in records]
        if len(records) < 15:
            continue

        dep, dst = q.departure, q.destination
        for t in range(3, len(records) - 1):
            past = records[:t + 1]
            rec_date_str = records[t + 1].get("date", "")
            feats = extract_features(
                records=past,
                days_until_departure=14,
                departure_city=dep,
                destination_city=dst,
                departure_date=rec_date_str,
                holidays=[],
                time_index=0.5,
            )
            all_X.append(feats)
            all_y.append(records[t + 1].get("price", 0))

        # Print sample features for first route
        if len(all_X) > 0:
            print(f"Route: {dep}->{dst} ({len(records)} records)")
            x = all_X[-1]
            new_feats = ["price_change_1d", "price_change_3d", "rolling_mean_3d", "rolling_std_3d",
                         "days_until_departure_sq", "is_weekend", "is_holiday_period", "price_momentum"]
            for name in new_feats:
                print(f"  {name:<35} {x.get(name, 0):.6f}")
            print()

    # Quick Ridge on sampled data
    if len(all_X) < 10:
        print("Not enough data")
        db.close(); return

    print(f"Total training samples: {len(all_X)}")

    # Sample if too many
    if len(all_X) > 10000:
        import random
        indices = random.sample(range(len(all_X)), 10000)
        X_sample = [all_X[i] for i in indices]
        y_sample = [all_y[i] for i in indices]
    else:
        X_sample, y_sample = all_X, all_y

    from sklearn.linear_model import Ridge
    import numpy as np

    X_mat = [[x.get(name, 0.0) for name in feature_names] for x in X_sample]
    model = Ridge(alpha=1.0)
    model.fit(np.array(X_mat), np.array(y_sample))

    preds = model.predict(X_mat)
    ss_res = sum((y_sample[i] - preds[i]) ** 2 for i in range(len(y_sample)))
    y_mean = statistics.mean(y_sample)
    ss_tot = sum((y - y_mean) ** 2 for y in y_sample)
    r2 = 1 - ss_res / max(ss_tot, 1e-10)
    rmse = (ss_res / len(y_sample)) ** 0.5
    print(f"R Ridge Inspection: R²={r2:.3f}, RMSE={rmse:.0f}")

    # Feature importance
    coef_imp = []
    for i, name in enumerate(feature_names):
        col = [row[i] for row in X_mat]
        col_std = statistics.stdev(col) if len(col) > 1 else 1.0
        importance = abs(model.coef_[i]) * col_std
        coef_imp.append((name, model.coef_[i], importance))
    coef_imp.sort(key=lambda x: -x[2])

    print(f"\n{'Feature':<35} {'Coef':>10} {'|Coef|*Std':>10}")
    print("-" * 57)
    for name, coef, imp in coef_imp[:15]:
        marker = " <-- NEW" if name in {"price_change_1d", "price_change_3d", "rolling_mean_3d",
                                          "rolling_std_3d", "days_until_departure_sq",
                                          "is_weekend", "is_holiday_period", "price_momentum"} else ""
        print(f"{name:<35} {coef:>10.4f} {imp:>10.4f}{marker}")

    db.close()

if __name__ == "__main__":
    main()
