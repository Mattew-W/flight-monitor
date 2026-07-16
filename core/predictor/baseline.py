"""
Flight Monitor — Linear Baseline Models
========================================

PDF Reference: §6.1 — "线性回归与基准模型"

Provides OLS, Ridge, and Lasso baselines for benchmarking.
These serve as the "minimum viable model" — any tree ensemble
must outperform these to justify its complexity.

Key design decisions:
  - Ridge is the default (handles multicollinearity in engineered features)
  - StandardScaler is applied before all linear models
  - Graceful fallback to mean-predictor when sklearn is unavailable
"""
import logging
import math
import statistics
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_HAS_SKLEARN = False
try:
    import numpy as np
    from sklearn.linear_model import Lasso, LinearRegression, Ridge
    from sklearn.preprocessing import StandardScaler

    _HAS_SKLEARN = True
except ImportError:
    pass


class LinearBaseline:
    """Linear regression baseline with optional L1/L2 regularization.

    Usage:
        model = LinearBaseline(model_type="ridge", alpha=1.0)
        model.fit(X, y)
        preds = model.predict(X_test)
        metrics = model.evaluate(X_val, y_val)
    """

    def __init__(self, model_type: str = "ridge", alpha: float = 1.0):
        """
        Args:
            model_type: "ols", "ridge", or "lasso".
            alpha: Regularization strength (>0). Ignored for "ols".
                   Higher alpha → stronger regularization → simpler model.
        """
        if model_type not in ("ols", "ridge", "lasso"):
            raise ValueError(
                f"Unknown model_type '{model_type}'. Use 'ols', 'ridge', or 'lasso'."
            )
        self.model_type = model_type
        self.alpha = alpha
        self.model = None
        self.scaler = StandardScaler() if _HAS_SKLEARN else None
        self._is_fitted = False
        self._mean_y = 0.0           # fallback when sklearn missing
        self._feature_names: Optional[List[str]] = None

    # ── Training ──────────────────────────────────────────

    def fit(
        self,
        X: List[List[float]],
        y: List[float],
        feature_names: Optional[List[str]] = None,
    ):
        """Fit linear model to training data.

        Args:
            X: 2D list of feature vectors, shape (n_samples, n_features).
            y: Target prices.
            feature_names: Optional names for coefficient inspection.
        """
        if not X or not y:
            logger.warning("Empty training data, skipping fit")
            self._mean_y = 0.0
            return

        if len(X) != len(y):
            raise ValueError(
                f"X and y must have same length, got {len(X)} vs {len(y)}"
            )

        self._feature_names = feature_names
        self._mean_y = statistics.mean(y)

        if not _HAS_SKLEARN:
            logger.warning(
                "sklearn not available; LinearBaseline will predict the mean (%.0f)",
                self._mean_y,
            )
            self._is_fitted = True
            return

        try:
            import numpy as np

            X_arr = np.array(X, dtype=float)
            y_arr = np.array(y, dtype=float)

            # Replace inf/nan with 0
            X_arr = np.nan_to_num(X_arr, nan=0.0, posinf=0.0, neginf=0.0)
            y_arr = np.nan_to_num(y_arr, nan=self._mean_y)

            if self.model_type == "ols":
                self.model = LinearRegression()
            elif self.model_type == "ridge":
                self.model = Ridge(alpha=self.alpha, random_state=42)
            elif self.model_type == "lasso":
                self.model = Lasso(
                    alpha=self.alpha,
                    max_iter=5000,
                    random_state=42,
                    selection="random",
                )

            X_scaled = self.scaler.fit_transform(X_arr)
            self.model.fit(X_scaled, y_arr)
            self._is_fitted = True

            # Log top coefficients (for interpretability)
            n_coefs = len(self.model.coef_) if hasattr(self.model, "coef_") else 0
            if n_coefs > 0 and self._feature_names:
                coefs_sorted = sorted(
                    zip(self._feature_names[:n_coefs], self.model.coef_),
                    key=lambda x: abs(x[1]),
                    reverse=True,
                )
                top5 = coefs_sorted[:5]
                logger.info(
                    "LinearBaseline (%s) fitted on %d samples. Top features: %s",
                    self.model_type,
                    len(X),
                    ", ".join(f"{n}={c:.1f}" for n, c in top5),
                )

        except Exception as e:
            logger.error("LinearBaseline fit failed: %s", e)
            self._is_fitted = False

    # ── Prediction ────────────────────────────────────────

    def predict(self, X: List[List[float]]) -> List[float]:
        """Predict prices.

        Args:
            X: Feature vectors to predict on.

        Returns:
            Predicted prices (same length as X).
        """
        if not X:
            return []

        if not self._is_fitted or not _HAS_SKLEARN or self.model is None:
            # Fallback: predict mean
            return [self._mean_y] * len(X)

        try:
            import numpy as np

            X_arr = np.array(X, dtype=float)
            X_arr = np.nan_to_num(X_arr, nan=0.0, posinf=0.0, neginf=0.0)
            X_scaled = self.scaler.transform(X_arr)
            preds = self.model.predict(X_scaled).tolist()
            # Clip negative predictions
            return [max(0.0, p) for p in preds]
        except Exception as e:
            logger.error("LinearBaseline predict failed: %s", e)
            return [self._mean_y] * len(X)

    # ── Evaluation ────────────────────────────────────────

    def evaluate(
        self, X: List[List[float]], y: List[float]
    ) -> Dict[str, float]:
        """Evaluate model on validation data.

        Returns dict with keys: rmse, mae, r2, mape.
        """
        if not X or not y:
            return {"rmse": 0.0, "mae": 0.0, "r2": 0.0, "mape": 0.0}

        preds = self.predict(X)
        n = len(y)
        if n == 0:
            return {"rmse": 0.0, "mae": 0.0, "r2": 0.0, "mape": 0.0}

        # MAE
        mae = sum(abs(y[i] - preds[i]) for i in range(n)) / n

        # RMSE
        sq_errors = [(y[i] - preds[i]) ** 2 for i in range(n)]
        rmse = math.sqrt(sum(sq_errors) / n)

        # R²
        y_mean = statistics.mean(y)
        ss_res = sum(sq_errors)
        ss_tot = sum((yi - y_mean) ** 2 for yi in y)
        r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        # MAPE
        mape = 0.0
        valid_count = 0
        for i in range(n):
            if abs(y[i]) > 1e-6:
                mape += abs(y[i] - preds[i]) / abs(y[i])
                valid_count += 1
        mape = (mape / valid_count * 100) if valid_count > 0 else 0.0

        return {
            "rmse": round(rmse, 2),
            "mae": round(mae, 2),
            "r2": round(r2, 4),
            "mape": round(mape, 2),
        }

    def get_coefficients(self) -> Optional[Dict[str, float]]:
        """Return feature → coefficient mapping for interpretability."""
        if (
            not self._is_fitted
            or not _HAS_SKLEARN
            or self.model is None
            or not hasattr(self.model, "coef_")
            or not self._feature_names
        ):
            return None

        return {
            name: round(float(coef), 4)
            for name, coef in zip(
                self._feature_names[: len(self.model.coef_)],
                self.model.coef_,
            )
        }
