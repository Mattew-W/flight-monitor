"""
Flight Monitor — Price Predictor v3 (Subpackage)
=================================================

Unified prediction engine based on PDF design guide:
  - Indian prior extraction → universal behavioral patterns
  - Complete feature engineering (35 features)
  - Ensemble models: GBR + Ridge + RF
  - Walk-Forward validation with Purge Gap
  - Multi-model benchmarking
  - Fuel price integration (PDF §3.2)

Exports:
  - PricePredictorV3: Main predictor (cold start → online learning)
  - LinearBaseline: Ridge/Lasso/OLS baselines (PDF §6.1)
  - ModelBenchmark: Multi-model comparison (PDF §6.2)
  - FuelPriceProvider: Jet fuel data interface (PDF §3.2)
  - extract_features: Standalone feature extraction
"""
from .indian_prior import IndianPriorExtractor
from .features import _get_feature_names, extract_features
from .distance import get_distance, get_distance_with_fallback
from .predictor_v3 import PricePredictorV3
from .fuel_data import FuelPriceProvider
from .baseline import LinearBaseline
from .benchmark import ModelBenchmark

__all__ = [
    "PricePredictorV3",
    "IndianPriorExtractor",
    "LinearBaseline",
    "ModelBenchmark",
    "FuelPriceProvider",
    "extract_features",
    "_get_feature_names",
    "get_distance",
    "get_distance_with_fallback",
]
