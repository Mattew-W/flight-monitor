"""
Flight Monitor - Config Package (S3)
=====================================
JSON-based configuration loader.

Usage:
    from config import get_config
    cfg = get_config()

    # Access config data:
    platforms = cfg.platforms
    city_codes = cfg.city_codes
    routes = cfg.popular_routes
"""

import importlib.util
import os as _os

# ── S3: JSON loader ──────────────────────────────────────────
from config.loader import ConfigLoader, get_config, reload_config

# ── Backward compatibility: re-export all from config.py ──────
# The config.py module contains runtime settings (SMTP_*, DB_PATH, etc.)
# that are imported throughout the codebase. We re-export them here so
# that `from config import SMTP_HOST` continues to work even though
# config/ is now a package (which shadows config.py).
_config_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "config.py")
_spec = importlib.util.spec_from_file_location("_config_py_module", _config_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re-export all public names from config.py
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith('_')})

__all__ = ["ConfigLoader", "get_config", "reload_config"]
