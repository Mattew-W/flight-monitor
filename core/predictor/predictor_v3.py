"""
Flight Monitor — Price Predictor v3
====================================

A complete redesign of the price prediction engine based on:
  1. PDF design guide (feature engineering, walk-forward validation)
  2. Indian flight dataset priors (universal behavioral patterns)
  3. Modern sklearn GradientBoosting + RandomForest ensemble

Architecture:
  Phase 1 (offline): Extract priors from Indian data → save JSON
  Phase 2 (runtime):  Extract features → train ensemble → predict
  Phase 3 (feedback):  Online data fine-tunes priors over time

Usage:
    # Cold start (Indian priors only)
    p = PricePredictorV3(indian_priors="indian_priors.json")
    result = p.predict(flights, online_history, days_ahead=14, ...)

    # With online data (preferred)
    p = PricePredictorV3(indian_priors="indian_priors.json")
    p.fit_online(online_records, online_prices)
    result = p.predict(flights, online_history, days_ahead=14, ...)
"""
import json
import logging
import math
import os
import pickle
import statistics
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Lazy sklearn import with fallback
_HAS_SKLEARN = False
try:
    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import TimeSeriesSplit
    _HAS_SKLEARN = True
except ImportError:
    pass

from .features import extract_features, _get_feature_names


class PricePredictorV3:
    """Unified price predictor blending Indian priors with online data.

    Maintains TWO models:
      1. Prior model: Pre-trained on Indian data (universal patterns only)
      2. Online model: Trained on user's actual scrape data

    As online data grows, the prior model's weight decreases automatically.
    """

    # Indian prior coefficients (universal, from offline extraction)
    INDIAN_STOP_DISCOUNT = 0.18
    INDIAN_HOLIDAY_SURGE = 2.2
    INDIAN_LAST_MINUTE_SURGE = 1.4
    INDIAN_EARLY_BIRD_DISCOUNT = 0.85

    def __init__(self, indian_priors_path: Optional[str] = None):
        self.has_sklearn = _HAS_SKLEARN
        self.priors = {}
        # NOTE: StandardScaler was previously created but never wired into
        # fit/predict. Removed to avoid misleading code. If feature scaling is
        # needed later, add it explicitly in _fit_online_model / predict_online.
        self.online_model = None
        self.prior_model = None
        self._is_fitted = False
        self._is_prior_fitted = False

        if indian_priors_path and os.path.exists(indian_priors_path):
            with open(indian_priors_path, "r", encoding="utf-8") as f:
                self.priors = json.load(f)
            logger.info(f"Loaded Indian priors from {indian_priors_path}")
            self._fit_prior_model()

    def _fit_prior_model(self):
        """Create prior model from Indian data statistics."""
        stop_discount = self.priors.get("stop_discount", {}).get("average_stop_discount", self.INDIAN_STOP_DISCOUNT)
        airline_tier = self.priors.get("airline_classification", {}).get("per_airline", {})

        self.prior_model = {
            "stop_discount": stop_discount,
            "airline_tier_map": {al: info["tier"] for al, info in airline_tier.items()},
            "hour_ratios": self.priors.get("departure_time_pattern", {}).get("slot_ratios", {}),
        }
        self._is_prior_fitted = True
        logger.info(f"Prior model fitted (stop_discount={stop_discount})")

    # ── Training ────────────────────────────────────────────

    def fit_online(self, X: List[Dict], y: List[float]):
        """Train the online model with user's actual scrape data."""
        if not self.has_sklearn:
            logger.warning("sklearn not available, using prior model only")
            return

        if len(X) < 10:
            logger.warning(f"Only {len(X)} samples, waiting for more data")
            return

        feature_names = _get_feature_names()
        X_matrix = [[x.get(name, 0.0) for name in feature_names] for x in X]
        y_array = list(y)

        # Walk-forward validation to tune hyperparameters (only for GBR with enough data)
        best_score = -float('inf')
        best_params = {}
        if len(X) >= 50:
            best_params = self._tune_hyperparams(X_matrix, y_array)
        else:
            best_params = {"n_estimators": 50, "max_depth": 3, "learning_rate": 0.05}

        # Train final model
        self.online_model = self._build_model(**best_params, n_samples=len(X))
        self.online_model.fit(np.array(X_matrix), np.array(y_array))
        self._is_fitted = True

        # Evaluate
        preds = self.online_model.predict(X_matrix)
        ss_res = sum((y[i] - preds[i]) ** 2 for i in range(len(y)))
        ss_tot = sum((y[i] - statistics.mean(y)) ** 2 for i in range(len(y)))
        r2 = 1 - ss_res / max(ss_tot, 1e-10)
        rmse = math.sqrt(ss_res / len(y))

        logger.info(f"Online model fitted (n={len(X)}, R²={r2:.3f}, RMSE={rmse:.0f}, model={type(self.online_model).__name__})")

    def _tune_hyperparams(self, X, y, n_splits=3) -> Dict:
        """Walk-forward hyperparameter tuning."""
        tscv = TimeSeriesSplit(n_splits=n_splits)
        param_grid = [
            {"n_estimators": 50, "max_depth": 3, "learning_rate": 0.05},
            {"n_estimators": 100, "max_depth": 4, "learning_rate": 0.03},
            {"n_estimators": 100, "max_depth": 3, "learning_rate": 0.05},
            {"n_estimators": 200, "max_depth": 4, "learning_rate": 0.02},
        ]

        best_params = param_grid[0]
        best_score = -float('inf')

        for params in param_grid:
            fold_scores = []
            for train_idx, val_idx in tscv.split(X):
                if len(train_idx) < 10 or len(val_idx) < 5:
                    continue
                X_train = [X[i] for i in train_idx]
                y_train = [y[i] for i in train_idx]
                X_val = [X[i] for i in val_idx]
                y_val = [y[i] for i in val_idx]

                model = GradientBoostingRegressor(
                    n_estimators=params["n_estimators"],
                    max_depth=params["max_depth"],
                    learning_rate=params["learning_rate"],
                    subsample=0.8,
                    random_state=42,
                    min_samples_leaf=max(5, len(X) // 20),
                )
                model.fit(np.array(X_train), np.array(y_train))
                preds = model.predict(np.array(X_val))
                r2 = 1 - sum((y_val[i] - preds[i]) ** 2 for i in range(len(y_val))) / max(
                    sum((y_val[i] - statistics.mean(y_val)) ** 2 for i in range(len(y_val))), 1e-10)
                fold_scores.append(r2)

            score = statistics.mean(fold_scores) if fold_scores else -float('inf')
            if score > best_score:
                best_score = score
                best_params = params

        logger.info(f"Walk-forward tuning: best R²={best_score:.3f}, params={best_params}")
        return best_params

    def _build_model(self, n_estimators, max_depth, learning_rate, subsample=0.8, n_samples=None):
        """Build the sklearn model. Ridge for small samples, GBR for large."""
        if not self.has_sklearn:
            return None
        if n_samples is None:
            n_samples = 100
        # Ridge for small samples (regularization prevents overfitting)
        if n_samples < 50:
            return Ridge(alpha=1.0)
        # GBR for large samples (can capture nonlinear patterns)
        return GradientBoostingRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=subsample,
            random_state=42,
            min_samples_leaf=max(5, n_samples // 10),
        )

    # ── Prediction ──────────────────────────────────────────

    def predict(
        self,
        flights: List[Dict],
        online_history: List[Dict],
        days_ahead: int,
        departure_city: str = "",
        destination_city: str = "",
        departure_date: str = "",
        cabin_class: str = "economy",
        holidays: List = None,
    ) -> Dict:
        """Generate price forecast using combined models."""
        holidays = holidays or []

        # 1. Extract features
        features = extract_features(
            records=online_history,
            days_until_departure=days_ahead,
            departure_city=departure_city,
            destination_city=destination_city,
            cabin_class=cabin_class,
            departure_date=departure_date,
            holidays=holidays,
            airline_prior=self.priors,
        )

        # 2. Compute online-data weight
        data_weight = self._compute_data_weight(len(online_history))

        # 3. Prior-based prediction (always available)
        prior_pred, prior_lower, prior_upper = self._prior_predict(features, data_weight, flights)

        # 4. If online model is trained, blend predictions
        if self._is_fitted and self.online_model is not None:
            online_pred, online_lower, online_upper = self._online_predict(features, online_history)
            pred = prior_pred * (1 - data_weight) + online_pred * data_weight
            lower = prior_lower * (1 - data_weight) + online_lower * data_weight
            upper = prior_upper * (1 - data_weight) + online_upper * data_weight
            model_name = f"Blended (prior{(1-data_weight)*100:.0f}% + online{data_weight*100:.0f}%)"
        else:
            pred, lower, upper = prior_pred, prior_lower, prior_upper
            model_name = "Indian Prior (cold start)"

        # 5. Post-processing sanity checks
        pred = self._sanity_check(pred, features, flights)
        lower = max(0, lower)
        upper = max(lower + 1, upper)

        return {
            "forecast": pred,
            "lower_ci": lower,
            "upper_ci": upper,
            "model": model_name,
            "data_weight": round(data_weight, 2),
            "n_online_records": len(online_history),
            "features_used": len(features),
            "feature_vector": features,
        }

    def _prior_predict(self, features: Dict, data_weight: float, flights: List[Dict]) -> Tuple[float, float, float]:
        """Prior-based prediction using Indian behavioral patterns."""
        current = features.get("current_price", 0)
        if current <= 0 and flights:
            prices = [f.get("price", 0) for f in flights if f.get("price", 0) > 0]
            current = statistics.median(prices) if prices else 500

        days_left = features.get("days_left_raw", 0)
        holiday_prox = features.get("holiday_proximity", 0)
        stops = features.get("stop_count", 0)
        stop_discount = self.prior_model.get("stop_discount", self.INDIAN_STOP_DISCOUNT) if self.prior_model else self.INDIAN_STOP_DISCOUNT

        # Days-to-departure modifier (U-shaped from Indian data)
        days_modifier = self._days_to_departure_modifier(days_left)

        # Holiday multiplier
        holiday_modifier = 1.0 + (self.INDIAN_HOLIDAY_SURGE - 1.0) * holiday_prox

        # Stop discount
        stop_modifier = max(0.5, 1.0 - stop_discount * stops)

        predicted = current * days_modifier * holiday_modifier * stop_modifier

        # Uncertainty
        days_factor = 1 + days_left / 60.0
        lower = predicted * 0.75 / math.sqrt(days_factor)
        upper = predicted * 1.25 * math.sqrt(days_factor)

        return round(predicted), round(lower), round(upper)

    def _days_to_departure_modifier(self, days_left: int) -> float:
        """U-shaped price curve from Indian data."""
        if days_left <= 0:
            return 1.0
        if days_left >= 90:
            return 1.0
        elif days_left >= 60:
            return 0.9 + 0.1 * (60 - days_left) / 30
        elif days_left >= 14:
            return 0.8 + 0.05 * (60 - days_left) / 46
        else:
            return 0.85 + 0.55 * (14 - days_left) / 14

    def _sanity_check(self, predicted: float, features: Dict, flights: List[Dict]) -> float:
        """Post-processing sanity checks."""
        predicted = max(0, predicted)

        if flights:
            prices = [f.get("price", 0) for f in flights if f.get("price", 0) > 0]
            if prices:
                median = statistics.median(prices)
                predicted = min(predicted, median * 3)
                predicted = max(predicted, median * 0.3)

        return round(predicted)

    def _online_predict(self, features: Dict, history: List[Dict]) -> Tuple[float, float, float]:
        """Use trained online model for prediction."""
        if not self._is_fitted or self.online_model is None:
            return 0, 0, 0

        feature_names = _get_feature_names()
        X = [[features.get(name, 0.0) for name in feature_names]]
        pred = self.online_model.predict(np.array(X))[0]

        # Confidence from staged predictions
        if hasattr(self.online_model, "staged_predict"):
            try:
                staged = list(self.online_model.staged_predict(np.array(X)))
                # Each yield is array([value]) — extract scalar with [0]
                staged_values = []
                for s in staged:
                    try:
                        staged_values.append(float(s[0]) if hasattr(s, "__getitem__") else float(s))
                    except (TypeError, IndexError):
                        staged_values.append(float(s))
                if len(staged_values) >= 10:
                    pred_std = statistics.stdev(staged_values[-10:])
                else:
                    pred_std = pred * 0.15
            except Exception:
                pred_std = pred * 0.15
        else:
            pred_std = pred * 0.15

        lower = pred - 1.96 * pred_std
        upper = pred + 1.96 * pred_std

        return round(max(0, pred)), round(max(0, lower)), round(upper)

    def _compute_data_weight(self, n_records: int) -> float:
        """Compute weight for online model vs prior (0-1)."""
        if n_records < 5:
            return 0.0
        return min(1.0, max(0.1, 1 - math.exp(-n_records / 30.0)))

    # ── Walk-Forward Backtest ───────────────────────────────

    def backtest_walk_forward(
        self,
        records: List[Dict],
        departure_city: str,
        destination_city: str,
        holidays: List = None,
        n_splits: int = 5,
        min_train_size: int = 10,
        purge_gap: int = 1,
        departure_date: str = "",
    ) -> Dict:
        """Run walk-forward backtest on historical records.

        PDF §7.2: Uses Purge Gap between train and test to prevent
        autocorrelation leakage from high-frequency data collection.
        """
        holidays = holidays or []
        if len(records) < min_train_size + n_splits:
            return {"error": f"Need >= {min_train_size + n_splits} records, got {len(records)}"}

        sorted_records = sorted(records, key=lambda r: r.get("date", ""))

        fold_predictions = []
        fold_actuals = []

        # Expanding window: train on all past data, test on next chunk
        # This maximizes training data usage for small datasets
        usable = len(sorted_records) - min_train_size
        fold_size = max(2, usable // n_splits)

        for fold_i in range(n_splits):
            split_point = min_train_size + fold_i * fold_size
            if split_point >= len(sorted_records):
                break

            train_data = sorted_records[:split_point]
            # Purge Gap: exclude purge_gap days between train/test
            test_start = min(split_point + purge_gap, len(sorted_records))
            test_data = sorted_records[test_start:min(test_start + fold_size, len(sorted_records))]
            if not test_data:
                break

            # Build training data
            X_train, y_train = [], []
            for t in range(3, len(train_data) - 1):
                past = train_data[:t + 1]
                time_idx = (t + 1) / len(train_data)
                # Compute days_until_departure
                rec_date_str = train_data[t + 1].get("date", "")
                days_until = 14
                if departure_date and rec_date_str:
                    try:
                        dep_dt = datetime.strptime(departure_date, "%Y-%m-%d")
                        rec_dt = datetime.strptime(rec_date_str, "%Y-%m-%d")
                        days_until = max(0, (dep_dt - rec_dt).days)
                    except ValueError:
                        pass
                feats = extract_features(
                    records=past,
                    days_until_departure=days_until,
                    departure_city=departure_city,
                    destination_city=destination_city,
                    departure_date=rec_date_str,
                    holidays=holidays,
                    time_index=time_idx,
                )
                X_train.append(feats)
                y_train.append(train_data[t + 1].get("price", 0))

            if len(X_train) < 5:
                continue

            # Train model
            if self.has_sklearn and len(X_train) > 10:
                model = self._build_model(50, 3, 0.05, n_samples=len(X_train))
                feature_names = _get_feature_names()
                X_mat = [[x.get(name, 0.0) for name in feature_names] for x in X_train]
                model.fit(np.array(X_mat), np.array(y_train))

                # Test on future
                for test_record in test_data:
                    test_time_idx = (len(train_data) + test_data.index(test_record)) / len(sorted_records)
                    test_rec_date = test_record.get("date", "")
                    test_days_until = 14
                    if departure_date and test_rec_date:
                        try:
                            dep_dt = datetime.strptime(departure_date, "%Y-%m-%d")
                            rec_dt = datetime.strptime(test_rec_date, "%Y-%m-%d")
                            test_days_until = max(0, (dep_dt - rec_dt).days)
                        except ValueError:
                            pass
                    feats = extract_features(
                        records=train_data,
                        days_until_departure=test_days_until,
                        departure_city=departure_city,
                        destination_city=destination_city,
                        departure_date=test_rec_date,
                        holidays=holidays,
                        time_index=test_time_idx,
                    )
                    X_test = [[feats.get(name, 0.0) for name in feature_names]]
                    pred = model.predict(np.array(X_test))[0]
                    fold_predictions.append(pred)
                    fold_actuals.append(test_record.get("price", 0))
            else:
                # Fallback to prior-based
                for test_record in test_data:
                    fold_predictions.append(statistics.mean(y_train) if y_train else 500)
                    fold_actuals.append(test_record.get("price", 0))

        # Metrics
        if fold_actuals:
            mae = sum(abs(fold_actuals[i] - fold_predictions[i]) for i in range(len(fold_actuals))) / len(fold_actuals)
            rmse = math.sqrt(sum((fold_actuals[i] - fold_predictions[i]) ** 2 for i in range(len(fold_actuals))) / len(fold_actuals))
            mean_actual = statistics.mean(fold_actuals)
            mape = mae / mean_actual * 100 if mean_actual > 0 else 0
            ss_res = sum((fold_actuals[i] - fold_predictions[i]) ** 2 for i in range(len(fold_actuals)))
            ss_tot = sum((a - mean_actual) ** 2 for a in fold_actuals)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        else:
            mae = rmse = mape = r2 = 0

        return {
            "n_folds": n_splits,
            "n_predictions": len(fold_predictions),
            "mae": round(mae),
            "rmse": round(rmse),
            "mape": round(mape, 1),
            "r2": round(r2, 3),
            "purge_gap": purge_gap,
        }

    # ── Persistence ─────────────────────────────────────────

    def save(self, path: str):
        """Save trained model to disk."""
        data = {
            "priors": self.priors,
            "is_fitted": self._is_fitted,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        if self.online_model is not None and self.has_sklearn:
            model_path = path.replace(".json", "_sklearn.pkl")
            with open(model_path, "wb") as f:
                pickle.dump(self.online_model, f)
        logger.info(f"Model saved to {path}")

    def load(self, path: str):
        """Load trained model from disk."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.priors = data.get("priors", {})
        self._is_fitted = data.get("is_fitted", False)

        model_path = path.replace(".json", "_sklearn.pkl")
        if os.path.exists(model_path) and self.has_sklearn:
            with open(model_path, "rb") as f:
                self.online_model = pickle.load(f)
        
        # Rebuild prior model from loaded priors
        if self.priors:
            self._fit_prior_model()
        
        logger.info(f"Model loaded from {path}")

    # ── High-level API ─────────────────────────────────────

    def build_training_data(
        self,
        historical_records: List[Dict],
        departure: str,
        destination: str,
        holidays: List = None,
        departure_date: str = "",
    ) -> Tuple[List[Dict], List[float]]:
        """Build supervised training data from historical records."""
        holidays = holidays or []
        X, y = [], []
        # Skip first 3 samples: rolling_stats cannot be computed reliably
        for t in range(3, len(historical_records) - 1):
            past = historical_records[:t + 1]
            # time_index: normalized position in sequence (0..1) for trend learning
            time_idx = (t + 1) / len(historical_records)
            # Compute days_until_departure from departure_date - record_date
            rec_date_str = historical_records[t + 1].get("date", "")
            days_until = 14  # default
            if departure_date and rec_date_str:
                try:
                    dep_dt = datetime.strptime(departure_date, "%Y-%m-%d")
                    rec_dt = datetime.strptime(rec_date_str, "%Y-%m-%d")
                    days_until = max(0, (dep_dt - rec_dt).days)
                except ValueError:
                    pass
            feats = extract_features(
                records=past,
                days_until_departure=days_until,
                departure_city=departure,
                destination_city=destination,
                departure_date=rec_date_str,
                holidays=holidays,
                time_index=time_idx,
            )
            X.append(feats)
            y.append(historical_records[t + 1].get("price", 0))
        return X, y
