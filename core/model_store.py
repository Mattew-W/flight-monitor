"""
Flight Monitor — Model Store (M4)
==================================

Versioned model persistence for trained PricePredictorV3 models.

Each version is a directory: models/query_{id}/v{N}/
  ├── metadata.json   — training info, metrics, timestamps
  └── sklearn.pkl     — pickled sklearn model (GradientBoostingRegressor etc.)

The Indian priors JSON is referenced (not duplicated) per version.

Thread-safe: uses file locks via threading.Lock for concurrent access.
"""
import json
import logging
import os
import pickle
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default storage root. Override via ModelStore(root=...) if needed.
DEFAULT_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

# Minimum online records needed to train a new version
MIN_RECORDS_FOR_TRAINING = 10


class ModelStore:
    """Versioned model storage with rollback support.

    Usage:
        store = ModelStore()
        store.save_version(query_id=42, predictor, metrics={"r2": 0.85})
        latest = store.load_latest(query_id=42)
        versions = store.list_versions(query_id=42)
    """

    def __init__(self, root: str = DEFAULT_MODELS_DIR):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._lock = threading.RLock()

    def _query_dir(self, query_id: int) -> str:
        d = os.path.join(self.root, f"query_{query_id}")
        os.makedirs(d, exist_ok=True)
        return d

    def _version_path(self, query_id: int, version: int, ext: str) -> str:
        return os.path.join(self._query_dir(query_id), f"v{version}", f"model.{ext}")

    def _save_metadata(self, query_id: int, version: int, metadata: Dict):
        meta_path = os.path.join(self._query_dir(query_id), f"v{version}", "metadata.json")
        os.makedirs(os.path.dirname(meta_path), exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2, default=str)

    def _load_metadata(self, query_id: int, version: int) -> Optional[Dict]:
        meta_path = os.path.join(self._query_dir(query_id), f"v{version}", "metadata.json")
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # Corrupted metadata shouldn't crash list_versions / load_latest.
            logger.warning(f"Corrupted metadata for query={query_id} v{version}: {e}")
            return None

    def save_version(
        self,
        query_id: int,
        predictor,  # PricePredictorV3
        metrics: Optional[Dict] = None,
        description: str = "",
    ) -> int:
        """Save a new version of the model. Returns the new version number.

        The full PricePredictorV3 is persisted via its own save() method.
        We also write a metadata.json with metrics + timestamp.
        """
        metrics = metrics or {}
        with self._lock:
            next_version = self._next_version(query_id)
            version_dir = os.path.join(self._query_dir(query_id), f"v{next_version}")
            os.makedirs(version_dir, exist_ok=True)

            # 1. Save the full predictor via its own save() — produces model.json + model_sklearn.pkl
            model_json_path = os.path.join(version_dir, "model.json")
            predictor.save(model_json_path)

            # 2. Write metadata
            meta = {
                "version": next_version,
                "query_id": query_id,
                "created_at": datetime.now().isoformat(),
                "description": description,
                "metrics": metrics,
                "has_online_model": predictor.online_model is not None,
                "n_priors_loaded": len(predictor.priors) if isinstance(predictor.priors, dict) else 0,
            }
            self._save_metadata(query_id, next_version, meta)

            logger.info(
                f"Model query={query_id} v{next_version} saved "
                f"(online_model={meta['has_online_model']}, R²={metrics.get('r2', 'N/A')})"
            )
            return next_version

    def load_version(self, query_id: int, version: int):
        """Load a specific version of PricePredictorV3. Returns None on failure."""
        from core.predictor import PricePredictorV3

        model_json_path = os.path.join(self._query_dir(query_id), f"v{version}", "model.json")
        if not os.path.exists(model_json_path):
            return None

        try:
            p = PricePredictorV3()
            p.load(model_json_path)
            return p
        except Exception as e:
            logger.error(f"Failed to load model query={query_id} v{version}: {e}")
            return None

    def load_latest(self, query_id: int):
        """Load the latest version. Returns None if no versions exist."""
        versions = self.list_versions(query_id)
        if not versions:
            return None
        latest = versions[-1]["version"]
        return self.load_version(query_id, latest)

    def delete_version(self, query_id: int, version: int) -> bool:
        """Delete a version directory. Returns True if successful."""
        import shutil
        version_dir = os.path.join(self._query_dir(query_id), f"v{version}")
        if not os.path.isdir(version_dir):
            return False
        with self._lock:
            try:
                shutil.rmtree(version_dir)
                logger.info(f"Deleted model query={query_id} v{version}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete model query={query_id} v{version}: {e}")
                return False

    def list_versions(self, query_id: int) -> List[Dict]:
        """List all versions with metadata, sorted ascending."""
        query_dir = self._query_dir(query_id)
        versions = []
        if not os.path.isdir(query_dir):
            return versions
        for name in sorted(os.listdir(query_dir)):
            if not name.startswith("v"):
                continue
            try:
                ver = int(name[1:])
            except ValueError:
                continue
            meta = self._load_metadata(query_id, ver)
            if meta:
                versions.append(meta)
        return versions

    def compare_versions(
        self, query_id: int, v1: int, v2: int
    ) -> Dict:
        """Compare metrics of two versions."""
        m1 = self._load_metadata(query_id, v1) or {}
        m2 = self._load_metadata(query_id, v2) or {}
        metrics1 = m1.get("metrics", {})
        metrics2 = m2.get("metrics", {})
        diff = {}
        all_keys = set(metrics1.keys()) | set(metrics2.keys())
        for key in sorted(all_keys):
            a = metrics1.get(key)
            b = metrics2.get(key)
            diff[key] = {"v": v1, "value": a}
            diff[key][f"v{v2}"] = b
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                diff[key]["delta"] = round(b - a, 4)
        return diff

    def get_best_version(self, query_id: int, metric: str = "r2") -> Optional[int]:
        """Return version number with the best metric (default: highest r2)."""
        versions = self.list_versions(query_id)
        if not versions:
            return None
        best_ver = None
        best_val = -float("inf")
        for v in versions:
            val = v.get("metrics", {}).get(metric)
            if isinstance(val, (int, float)) and val > best_val:
                best_val = val
                best_ver = v["version"]
        return best_ver

    def rollback(self, query_id: int, version: int) -> bool:
        """Rollback: delete all versions newer than `version`, making it the latest."""
        with self._lock:
            versions = self.list_versions(query_id)
            if not versions:
                return False
            target_exists = any(v["version"] == version for v in versions)
            if not target_exists:
                logger.error(f"Rollback failed: v{version} not found for query {query_id}")
                return False
            deleted = 0
            for v in versions:
                if v["version"] > version:
                    if self.delete_version(query_id, v["version"]):
                        deleted += 1
            logger.info(f"Rollback query={query_id}: deleted {deleted} versions, v{version} is now latest")
            return True

    def _next_version(self, query_id: int) -> int:
        versions = self.list_versions(query_id)
        if not versions:
            return 1
        return max(v["version"] for v in versions) + 1