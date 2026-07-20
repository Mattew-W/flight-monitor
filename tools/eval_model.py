"""
Model Evaluation & Tuning for Flight Monitor
=============================================
Performs comprehensive data quality checks, 70/30 holdout evaluation,
and alpha tuning for the PricePredictorV3 with Ridge regression.
"""
import sqlite3
import sys
import os
import statistics
import math
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from core.predictor.features import extract_features, _get_feature_names


def load_mock_data(db_path: str):
    """Load mock (synthetic) data grouped by route."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute('''
        SELECT sq.departure, sq.destination, sq.departure_date,
               pr.id, pr.airline, pr.flight_no, pr.aircraft,
               pr.departure_time, pr.arrival_time, pr.duration,
               pr.stops, pr.price, pr.cabin_class, pr.source,
               pr.recorded_at, pr.batch_id, pr.sub_class,
               pr.seat_inventory, pr.is_mock
        FROM price_records pr
        JOIN search_queries sq ON pr.query_id = sq.id
        WHERE pr.is_mock = 1
        ORDER BY pr.recorded_at ASC
    ''')

    route_data = {}
    for row in cur.fetchall():
        route_key = f"{row['departure']}->{row['destination']}"
        if route_key not in route_data:
            route_data[route_key] = {
                'departure': row['departure'],
                'destination': row['destination'],
                'records': []
            }
        record = {
            'price': row['price'],
            'airline': row['airline'],
            'flight_no': row['flight_no'],
            'aircraft': row['aircraft'],
            'departure_time': row['departure_time'],
            'arrival_time': row['arrival_time'],
            'duration': row['duration'],
            'stops': row['stops'],
            'cabin_class': row['cabin_class'],
            'source': row['source'],
            'recorded_at': row['recorded_at'],
            'batch_id': row['batch_id'],
            'sub_class': row['sub_class'],
            'seat_inventory': row['seat_inventory'],
            'is_mock': row['is_mock'],
            'departure_date': row['departure_date'],
        }
        route_data[route_key]['records'].append(record)

    conn.close()
    return route_data


def extract_training_data(records: List[Dict], departure: str, destination: str,
                          departure_date: str = ''):
    """Build (X, y) training matrix from time-ordered records."""
    feat_names = _get_feature_names()
    X_list = []
    y_list = []

    for t in range(5, len(records) - 1):
        past = records[:t]
        future = records[t]

        time_idx = t / len(records)
        rec_date = future.get('recorded_at', '')[:10]

        # Compute days_until_departure
        days_until = 14  # default
        if departure_date:
            try:
                dep_dt = datetime.strptime(departure_date[:10], "%Y-%m-%d")
                rec_dt = datetime.strptime(rec_date, "%Y-%m-%d")
                if rec_dt:
                    days_until = max(0, (dep_dt - rec_dt).days)
            except (ValueError, TypeError):
                pass

        feats = extract_features(
            records=past,
            days_until_departure=days_until,
            departure_city=departure,
            destination_city=destination,
            departure_date=rec_date,
            holidays=[],
            time_index=time_idx,
        )

        feat_vec = [feats.get(name, 0.0) for name in feat_names]
        X_list.append(feat_vec)
        y_list.append(future.get('price', 0))

    return np.array(X_list), np.array(y_list)


def evaluate_route(X, y, alpha=1.0, train_ratio=0.7):
    """70/30 holdout split and Ridge regression evaluation."""
    n = len(X)
    split_point = max(5, int(n * train_ratio))

    if split_point < 5 or (n - split_point) < 3:
        return None

    X_train = X[:split_point]
    y_train = y[:split_point]
    X_test = X[split_point:]
    y_test = y[split_point:]

    # Standardize
    scaler = StandardScaler(with_mean=True, with_std=True)
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    # Train
    model = Ridge(alpha=alpha)
    model.fit(X_train_s, y_train)

    # Predict
    preds = model.predict(X_test_s)

    # Metrics
    n_test = len(y_test)
    mae = sum(abs(y_test[i] - preds[i]) for i in range(n_test)) / n_test
    rmse = math.sqrt(sum((y_test[i] - preds[i]) ** 2 for i in range(n_test)) / n_test)
    mean_actual = np.mean(y_test)
    mape = mae / mean_actual * 100 if mean_actual > 0 else 0

    ss_res = sum((y_test[i] - preds[i]) ** 2 for i in range(n_test))
    ss_tot = sum((a - mean_actual) ** 2 for a in y_test)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return {
        'r2': r2,
        'rmse': rmse,
        'mae': mae,
        'mape': mape,
        'n_train': split_point,
        'n_test': n_test,
    }


def data_quality_report(route_data: Dict):
    """Phase 1: Data quality report."""
    print("=" * 80)
    print("PHASE 1: DATA QUALITY VALIDATION")
    print("=" * 80)

    # Select top 20 routes by record count
    sorted_routes = sorted(route_data.items(), key=lambda x: len(x[1]['records']), reverse=True)[:20]
    total_records = sum(len(v['records']) for _, v in sorted_routes)
    print(f"\nUsing top 20 routes by total mock records ({total_records} records)\n")

    # Per-route statistics
    print(f"{'Route':<20} {'Records':>8} {'Mean':>8} {'StdDev':>8} {'Min':>8} {'Max':>8} {'Days':>5}")
    print("-" * 80)

    all_prices_by_dow = {i: [] for i in range(7)}
    all_prices_by_month = {}
    all_prices_summer = []
    all_prices_nonsummer = []

    for route_key, route_info in sorted_routes:
        records = route_info['records']
        prices = [r['price'] for r in records]
        mean_p = statistics.mean(prices)
        std_p = statistics.stdev(prices) if len(prices) > 1 else 0

        daily_avgs = {}
        for r in records:
            day = r['recorded_at'][:10]
            if day not in daily_avgs:
                daily_avgs[day] = []
            daily_avgs[day].append(r['price'])

        days = sorted(daily_avgs.keys())
        n_days = len(days)

        first_day = datetime.strptime(days[0], "%Y-%m-%d")
        last_day = datetime.strptime(days[-1], "%Y-%m-%d")

        # Simple trend: slope via linear regression on daily means
        if n_days >= 2:
            daily_means = [statistics.mean(daily_avgs[d]) for d in days]
            x_vals = [(datetime.strptime(d, "%Y-%m-%d") - first_day).days for d in days]
            x_mean = statistics.mean(x_vals)
            y_mean = statistics.mean(daily_means)
            ss_xy = sum((x_vals[i] - x_mean) * (daily_means[i] - y_mean) for i in range(n_days))
            ss_xx = sum((x_vals[i] - x_mean) ** 2 for i in range(n_days))
            slope = ss_xy / ss_xx if ss_xx > 0 else 0
        else:
            slope = 0

        print(f"{route_key:<20} {len(prices):>8} {mean_p:>8.0f} {std_p:>8.0f} "
              f"{min(prices):>8.0f} {max(prices):>8.0f} {n_days:>5}")

        # Collect prices by day-of-week (for reported day)
        for r in records:
            try:
                dt = datetime.strptime(r['recorded_at'][:10], "%Y-%m-%d")
                dow = dt.weekday()  # 0=Mon, 6=Sun
                all_prices_by_dow[dow].append(r['price'])

                month = dt.month
                if month not in all_prices_by_month:
                    all_prices_by_month[month] = []
                all_prices_by_month[month].append(r['price'])

                if month in (7, 8):
                    all_prices_summer.append(r['price'])
                else:
                    all_prices_nonsummer.append(r['price'])
            except (ValueError, TypeError):
                pass

    # Day-of-week effect
    print(f"\n{'Day-of-Week Effect':}")
    print(f"{'DOW':<10} {'Mean Price':>12} {'Count':>10}")
    print("-" * 35)
    dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for dow in range(7):
        if all_prices_by_dow[dow]:
            p = all_prices_by_dow[dow]
            print(f"{dow_names[dow]:<10} {statistics.mean(p):>12.0f} {len(p):>10}")

    # Seasonal effect
    print(f"\n{'Seasonal Effect (recorded_at):'}")
    print(f"{'Period':<20} {'Mean Price':>12} {'Count':>10}")
    print("-" * 45)
    if all_prices_summer:
        print(f"{'Summer (Jul-Aug)':<20} {statistics.mean(all_prices_summer):>12.0f} {len(all_prices_summer):>10}")
    if all_prices_nonsummer:
        print(f"{'Non-Summer':<20} {statistics.mean(all_prices_nonsummer):>12.0f} {len(all_prices_nonsummer):>10}")

    # Monthly effect
    print(f"\n{'Monthly Effect (recorded_at):'}")
    print(f"{'Month':<10} {'Mean Price':>12} {'Count':>10}")
    print("-" * 35)
    for month in sorted(all_prices_by_month.keys()):
        p = all_prices_by_month[month]
        print(f"{month:>2}月      {statistics.mean(p):>12.0f} {len(p):>10}")

    return sorted_routes


def model_evaluation(sorted_routes, route_data):
    """Phase 2: 70/30 holdout evaluation with Ridge(alpha=1.0)."""
    print("\n" + "=" * 80)
    print("PHASE 2: MODEL EVALUATION (70/30 holdout, Ridge alpha=1.0)")
    print("=" * 80)

    results = []
    print(f"\n{'Route':<20} {'R²':>8} {'RMSE':>8} {'MAE':>8} {'MAPE%':>8} {'Train':>6} {'Test':>6}")
    print("-" * 75)

    for route_key, route_info in sorted_routes:
        records = route_info['records']
        departure = route_info['departure']
        destination = route_info['destination']

        dep_date = records[0].get('departure_date', '') if records else ''

        try:
            X, y = extract_training_data(records, departure, destination, dep_date)
        except Exception as e:
            print(f"{route_key:<20} {'ERROR':>8} ({e})")
            continue

        if len(X) < 10:
            print(f"{route_key:<20} {'INSUFFICIENT DATA'}")
            continue

        metrics = evaluate_route(X, y, alpha=1.0, train_ratio=0.7)

        if metrics is None:
            print(f"{route_key:<20} {'SPLIT FAILED'}")
            continue

        results.append({
            'route': route_key,
            **metrics,
        })

        print(f"{route_key:<20} {metrics['r2']:>8.3f} {metrics['rmse']:>8.0f} "
              f"{metrics['mae']:>8.0f} {metrics['mape']:>7.1f}% "
              f"{metrics['n_train']:>6} {metrics['n_test']:>6}")

    # Summary
    if results:
        r2_vals = [r['r2'] for r in results]
        rmse_vals = [r['rmse'] for r in results]
        mae_vals = [r['mae'] for r in results]
        mape_vals = [r['mape'] for r in results]

        print("-" * 75)
        print(f"{'SUMMARY':<20} {'R²':>8} {'RMSE':>8} {'MAE':>8} {'MAPE%':>8}")
        print("-" * 75)
        print(f"{'Mean':<20} {statistics.mean(r2_vals):>8.3f} {statistics.mean(rmse_vals):>8.0f} "
              f"{statistics.mean(mae_vals):>8.0f} {statistics.mean(mape_vals):>7.1f}%")
        print(f"{'Median':<20} {statistics.median(r2_vals):>8.3f} {statistics.median(rmse_vals):>8.0f} "
              f"{statistics.median(mae_vals):>8.0f} {statistics.median(mape_vals):>7.1f}%")
        print(f"{'Worst':<20} {min(r2_vals):>8.3f} {max(rmse_vals):>8.0f} "
              f"{max(mae_vals):>8.0f} {max(mape_vals):>7.1f}%")
        print(f"{'Best':<20} {max(r2_vals):>8.3f} {min(rmse_vals):>8.0f} "
              f"{min(mae_vals):>8.0f} {min(mape_vals):>7.1f}%")

        # Count R² < 0 routes
        bad_routes = [r for r in results if r['r2'] < 0]
        print(f"\nRoutes with R² < 0: {len(bad_routes)}:")
        for r in bad_routes:
            print(f"  {r['route']}: R²={r['r2']:.3f}, RMSE={r['rmse']:.0f}, MAPE={r['mape']:.1f}%")

    return results


def alpha_tuning(sorted_routes, route_data, current_results):
    """Phase 3: Try different alpha values for R²<0 routes."""
    print("\n" + "=" * 80)
    print("PHASE 3: ALPHA TUNING (0.1, 1.0, 10.0)")
    print("=" * 80)

    bad_routes = [r for r in current_results if r['r2'] < 0]

    if not bad_routes:
        print("No routes with R² < 0. Running comparison on top routes...\n")
        # Run on top 5 routes for comparison
        target_results = current_results[:5]
    else:
        print(f"Analyzing {len(bad_routes)} routes with R² < 0...\n")
        target_results = bad_routes

    alpha_values = [0.1, 1.0, 10.0]

    for r_info in target_results:
        route_key = r_info['route']
        route_info = route_data[route_key]
        records = route_info['records']
        departure = route_info['departure']
        destination = route_info['destination']
        dep_date = records[0].get('departure_date', '') if records else ''

        try:
            X, y = extract_training_data(records, departure, destination, dep_date)
        except:
            continue

        if len(X) < 10:
            continue

        print(f"\nRoute: {route_key} (baseline R²={r_info['r2']:.3f})")
        print(f"  Alpha     R²      RMSE    MAE    MAPE%")
        print(f"  {'-'*45}")

        best_alpha = 1.0
        best_r2 = r_info['r2']

        for alpha in alpha_values:
            metrics = evaluate_route(X, y, alpha=alpha, train_ratio=0.7)
            if metrics is None:
                continue
            marker = ""
            if metrics['r2'] > best_r2:
                best_r2 = metrics['r2']
                best_alpha = alpha
                marker = " ← best"
            print(f"  {alpha:<8} {metrics['r2']:>7.3f} {metrics['rmse']:>7.0f} "
                  f"{metrics['mae']:>7.0f} {metrics['mape']:>6.1f}%{marker}")

        print(f"  Best alpha: {best_alpha} (R²={best_r2:.3f})")

        # Analysis for R² < 0
        if r_info['r2'] < 0:
            n = len(X)
            n_train = int(n * 0.7)

            print(f"\n  *** R² < 0 Root Cause Analysis for {route_key} ***")
            print(f"      Total samples: {n}, Train: {n_train}, Test: {n - n_train}")
            print(f"      Price range: [{min(y):.0f}, {max(y):.0f}], Mean: {statistics.mean(y):.0f}")

            # Check if test period has different price range
            y_arr = np.array(y)
            y_train = y_arr[:n_train]
            y_test = y_arr[n_train:]

            train_mean = np.mean(y_train)
            test_mean = np.mean(y_test)
            train_std = np.std(y_train)
            test_std = np.std(y_test)

            print(f"      Train mean={train_mean:.0f}, std={train_std:.0f}")
            print(f"      Test  mean={test_mean:.0f}, std={test_std:.0f}")

            if test_mean > train_mean * 1.3:
                print(f"      ⚠ Test period price JUMP (+{(test_mean/train_mean-1)*100:.0f}%)")
            elif test_mean < train_mean * 0.7:
                print(f"      ⚠ Test period price DROP ({(1-test_mean/train_mean)*100:.0f}%)")

            # Check feature stability
            X_arr = np.array(X)
            X_train = X_arr[:n_train]
            X_test = X_arr[n_train:]

            feat_names = _get_feature_names()
            unstable_feats = []
            for j, name in enumerate(feat_names):
                train_col = X_train[:, j]
                test_col = X_test[:, j]
                train_m = np.mean(train_col)
                test_m = np.mean(test_col)
                overall_std = np.std(X_arr[:, j])
                if overall_std > 0:
                    drift = abs(test_m - train_m) / overall_std
                    if drift > 1.0:
                        unstable_feats.append((name, drift))

            if unstable_feats:
                unstable_feats.sort(key=lambda x: -x[1])
                print(f"      Top unstable features:")
                for name, drift in unstable_feats[:5]:
                    print(f"        {name}: drift={drift:.2f}")
            else:
                print(f"      No significant feature drift detected")


def main():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'flight_monitor.db')
    print(f"Database: {db_path}")

    # Load data
    route_data = load_mock_data(db_path)
    print(f"Total routes loaded: {len(route_data)}")

    # Phase 1: Data Quality
    sorted_routes = data_quality_report(route_data)

    # Phase 2: Model Evaluation
    results = model_evaluation(sorted_routes, route_data)

    # Phase 3: Alpha Tuning
    if results:
        alpha_tuning(sorted_routes, route_data, results)

    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    main()
