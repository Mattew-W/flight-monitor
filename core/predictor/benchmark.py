"""
Flight Monitor — Multi-Model Benchmarking
==========================================

PDF Reference: §6 — "算法架构评估"

Compares multiple prediction models on walk-forward time-series splits:
  - Linear Ridge (baseline)
  - Random Forest (ensemble bagging)
  - Gradient Boosting (ensemble boosting)

Key design:
  - All models share identical walk-forward folds (fair comparison)
  - Purge Gap enforced between train/test per PDF §7.2
  - Reports RMSE, MAE, MAPE, R² per model per fold
"""
import logging
import statistics
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor

    _HAS_SKLEARN = True
except ImportError:
    pass

from .baseline import LinearBaseline
from .features import _get_feature_names


class ModelBenchmark:
    """Benchmark multiple models using walk-forward time-series splits.

    Usage:
        bench = ModelBenchmark(n_splits=5, purge_gap=1, min_train_size=20)
        results = bench.run(X, y, feature_names)
        print(bench.summary())
    """

    def __init__(
        self,
        n_splits: int = 5,
        purge_gap: int = 1,
        min_train_size: int = 20,
        models: Optional[List[str]] = None,
    ):
        """
        Args:
            n_splits: Number of walk-forward folds.
            purge_gap: Days gap between train and test (PDF §7.2).
            min_train_size: Minimum samples for training.
            models: Which models to benchmark. Default: all 3.
        """
        self.n_splits = n_splits
        self.purge_gap = purge_gap
        self.min_train_size = min_train_size
        self.models_to_run = models or ["ridge", "random_forest", "gradient_boosting"]
        self.results: Dict[str, Dict] = {}

    # ── Main API ──────────────────────────────────────────

    def run(
        self,
        X: List[List[float]],
        y: List[float],
        feature_names: Optional[List[str]] = None,
    ) -> Dict:
        """Run full benchmark across all specified models.

        Args:
            X: Feature vectors (chronological order required!).
            y: Target prices (same order as X).
            feature_names: Names for feature columns.

        Returns:
            Nested dict: {model_name: {fold_metrics: [...], aggregate: {...}}}
        """
        if len(X) != len(y):
            raise ValueError(
                f"X and y must have same length: {len(X)} vs {len(y)}"
            )

        if len(X) < self.min_train_size + self.n_splits:
            logger.warning(
                "Not enough data for benchmarking: %d samples, need >= %d",
                len(X),
                self.min_train_size + self.n_splits,
            )
            return {}

        feature_names = feature_names or _get_feature_names()

        # Generate walk-forward splits (consistent across all models)
        splits = self._generate_splits(len(X))

        for model_name in self.models_to_run:
            if not _HAS_SKLEARN and model_name != "ridge":
                logger.warning(
                    "sklearn not available, skipping %s", model_name
                )
                continue

            self.results[model_name] = self._benchmark_one(
                model_name, X, y, feature_names, splits
            )

        return self.results

    def summary(self) -> str:
        """Return a human-readable summary table."""
        if not self.results:
            return "No benchmark results available."

        lines = []
        header = f"{'Model':<22} {'RMSE':>8} {'MAE':>8} {'MAPE(%)':>9} {'R²':>8} {'Folds':>6}"
        sep = "-" * len(header)
        lines.append(header)
        lines.append(sep)

        # Sort by RMSE ascending (best first)
        sorted_models = sorted(
            self.results.items(),
            key=lambda kv: kv[1].get("aggregate", {}).get("rmse", float("inf")),
        )

        for name, result in sorted_models:
            agg = result.get("aggregate", {})
            lines.append(
                f"{name:<22} "
                f"{agg.get('rmse', 0):>8.1f} "
                f"{agg.get('mae', 0):>8.1f} "
                f"{agg.get('mape', 0):>8.2f} "
                f"{agg.get('r2', 0):>8.4f} "
                f"{result.get('n_folds', 0):>6}"
            )

        lines.append(sep)

        if len(self.results) >= 2:
            # Show winner
            winner = sorted_models[0]
            lines.append(
                f"Winner: {winner[0]} "
                f"(RMSE={winner[1]['aggregate']['rmse']:.1f})"
            )

        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────

    def _generate_splits(
        self, n_samples: int
    ) -> List[Tuple[int, int, int]]:
        """Generate walk-forward split indices.

        Returns list of (train_end, test_start, test_end) tuples.
        train_end is exclusive (index at which training stops).
        test_start includes purge_gap offset.
        """
        splits = []
        fold_size = max(
            1, (n_samples - self.min_train_size) // self.n_splits
        )

        for fold_i in range(self.n_splits):
            train_end = self.min_train_size + fold_i * fold_size
            if train_end >= n_samples:
                break

            test_start = min(train_end + self.purge_gap, n_samples)
            test_end = min(test_start + fold_size, n_samples)

            if test_start >= test_end:
                break

            splits.append((train_end, test_start, test_end))

        return splits

    def _benchmark_one(
        self,
        model_name: str,
        X: List[List[float]],
        y: List[float],
        feature_names: List[str],
        splits: List[Tuple[int, int, int]],
    ) -> Dict:
        """Run benchmark for a single model across all folds."""
        fold_mae = []
        fold_rmse = []
        fold_r2 = []
        fold_mape = []

        for train_end, test_start, test_end in splits:
            X_train = X[:train_end]
            y_train = y[:train_end]
            X_test = X[test_start:test_end]
            y_test = y[test_start:test_end]

            if len(X_train) < 5 or len(X_test) < 2:
                continue

            # Build & train model
            model = self._build_model(model_name)
            y_pred = self._train_and_predict(
                model, model_name, X_train, y_train, X_test, feature_names
            )

            # Evaluate
            mae = self._mae(y_test, y_pred)
            rmse = self._rmse(y_test, y_pred)
            r2 = self._r2(y_test, y_pred)
            mape = self._mape(y_test, y_pred)

            fold_mae.append(mae)
            fold_rmse.append(rmse)
            fold_r2.append(r2)
            fold_mape.append(mape)

        if not fold_mae:
            return {"n_folds": 0, "aggregate": {}}

        return {
            "n_folds": len(fold_mae),
            "fold_metrics": {
                "mae": fold_mae,
                "rmse": fold_rmse,
                "r2": fold_r2,
                "mape": fold_mape,
            },
            "aggregate": {
                "mae": round(statistics.mean(fold_mae), 2),
                "rmse": round(statistics.mean(fold_rmse), 2),
                "r2": round(statistics.mean(fold_r2), 4),
                "mape": round(statistics.mean(fold_mape), 2),
            },
        }

    def _build_model(self, model_name: str):
        """Build model instance by name."""
        if model_name == "ridge":
            return LinearBaseline(model_type="ridge", alpha=1.0)
        elif model_name == "random_forest":
            if not _HAS_SKLEARN:
                return None
            return RandomForestRegressor(
                n_estimators=100,
                max_depth=6,
                min_samples_leaf=5,
                random_state=42,
                n_jobs=-1,
            )
        elif model_name == "gradient_boosting":
            if not _HAS_SKLEARN:
                return None
            return GradientBoostingRegressor(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                random_state=42,
                min_samples_leaf=3,
            )
        else:
            raise ValueError(f"Unknown model: {model_name}")

    def _train_and_predict(
        self,
        model,
        model_name: str,
        X_train: List[List[float]],
        y_train: List[float],
        X_test: List[List[float]],
        feature_names: List[str],
    ) -> List[float]:
        """Train model and return predictions."""

        if model_name == "ridge":
            model.fit(X_train, y_train, feature_names)
            return model.predict(X_test)
        elif _HAS_SKLEARN:
            import numpy as np

            X_arr = np.array(X_train, dtype=float)
            X_arr = np.nan_to_num(X_arr, nan=0.0, posinf=0.0, neginf=0.0)
            y_arr = np.array(y_train, dtype=float)
            y_arr = np.nan_to_num(y_arr, nan=statistics.mean(y_train))

            model.fit(X_arr, y_arr)

            X_test_arr = np.array(X_test, dtype=float)
            X_test_arr = np.nan_to_num(
                X_test_arr, nan=0.0, posinf=0.0, neginf=0.0
            )
            preds = model.predict(X_test_arr).tolist()
            return [max(0.0, p) for p in preds]

        # Fallback
        return [statistics.mean(y_train)] * len(X_test)

    # ── Metrics ───────────────────────────────────────────

    @staticmethod
    def _mae(actual: List[float], predicted: List[float]) -> float:
        n = len(actual)
        if n == 0:
            return 0.0
        return sum(abs(actual[i] - predicted[i]) for i in range(n)) / n

    @staticmethod
    def _rmse(actual: List[float], predicted: List[float]) -> float:
        import math

        n = len(actual)
        if n == 0:
            return 0.0
        sq = sum((actual[i] - predicted[i]) ** 2 for i in range(n))
        return math.sqrt(sq / n)

    @staticmethod
    def _r2(actual: List[float], predicted: List[float]) -> float:
        n = len(actual)
        if n <= 1:
            return 0.0
        mean_actual = statistics.mean(actual)
        ss_res = sum((actual[i] - predicted[i]) ** 2 for i in range(n))
        ss_tot = sum((ai - mean_actual) ** 2 for ai in actual)
        if ss_tot < 1e-10:
            return 0.0
        return 1.0 - (ss_res / ss_tot)

    @staticmethod
    def _mape(actual: List[float], predicted: List[float]) -> float:
        n = len(actual)
        if n == 0:
            return 0.0
        total = 0.0
        count = 0
        for a, p in zip(actual, predicted):
            if abs(a) > 1e-6:
                total += abs(a - p) / abs(a)
                count += 1
        return (total / count * 100) if count > 0 else 0.0
