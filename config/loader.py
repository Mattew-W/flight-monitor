"""
Flight Monitor - Config Loader (S3 Framework)
===============================================
Loads JSON configuration files and provides a unified interface.

Replaces hardcoded data in config.py with external JSON files:
  - platforms.json → PURCHASE_PLATFORMS
  - cities.json → CITY_CODES, CITY_GROUPS, CITY_TO_REGION
  - routes.json → POPULAR_ROUTES, ROUTE_AIRLINES
  - airlines.json → AIRLINES, AIRLINE_OFFICIAL_SITES, AIRLINE_CODES_EXTRA, AIRCRAFT_TYPES

Usage:
    from config.loader import get_config

    config = get_config()
    print(config.city_codes["北京"])  # "BJS"
    print(config.platforms["ctrip"]["name"])  # "携程旅行"
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


class ConfigLoader:
    """Loads and caches JSON configuration files."""

    def __init__(self, config_dir: str = None):
        self._config_dir = config_dir or DEFAULT_CONFIG_DIR
        self._cache: Dict[str, Any] = {}
        self._loaded = False

    def load(self) -> 'ConfigLoader':
        """Load all JSON config files into memory."""
        self._cache = {}
        config_files = {
            "platforms": "platforms.json",
            "cities": "cities.json",
            "routes": "routes.json",
            "airlines": "airlines.json",
        }
        for key, filename in config_files.items():
            filepath = os.path.join(self._config_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    self._cache[key] = json.load(f)
                logger.debug(f"ConfigLoader: loaded {filename}")
            except FileNotFoundError:
                logger.warning(f"ConfigLoader: {filename} not found at {filepath}")
                self._cache[key] = {}
            except json.JSONDecodeError as e:
                logger.error(f"ConfigLoader: {filename} JSON error: {e}")
                self._cache[key] = {}
        self._build_derived()
        self._loaded = True
        logger.info(f"ConfigLoader: all configs loaded from {self._config_dir}")
        return self

    def reload(self) -> 'ConfigLoader':
        """Reload all config files (hot-reload support)."""
        logger.info("ConfigLoader: reloading all configs")
        return self.load()

    def _build_derived(self):
        """Build derived/computed config values."""
        city_groups = self._cache.get("cities", {}).get("city_groups", {})
        city_to_region = {}
        for region, cities in city_groups.items():
            for city in cities:
                city_to_region[city] = region
        self._cache["city_to_region"] = city_to_region

        airlines_data = self._cache.get("airlines", {})
        domestic = airlines_data.get("domestic_airlines", [])
        international = airlines_data.get("international_airlines", [])
        self._cache["all_airlines"] = domestic + international

        aircraft = airlines_data.get("aircraft_types", {})
        all_aircraft = []
        for category in aircraft.values():
            all_aircraft.extend(category)
        self._cache["all_aircraft"] = all_aircraft

    @property
    def platforms(self) -> Dict[str, Any]:
        return self._cache.get("platforms", {}).get("platforms", {})

    @property
    def city_codes(self) -> Dict[str, str]:
        return self._cache.get("cities", {}).get("city_codes", {})

    @property
    def city_groups(self) -> Dict[str, List[str]]:
        return self._cache.get("cities", {}).get("city_groups", {})

    @property
    def city_to_region(self) -> Dict[str, str]:
        return self._cache.get("city_to_region", {})

    @property
    def popular_routes(self) -> List[Dict[str, str]]:
        return self._cache.get("routes", {}).get("popular_routes", [])

    @property
    def route_airlines(self) -> Dict[str, List[str]]:
        return self._cache.get("routes", {}).get("route_airlines", {})

    @property
    def domestic_airlines(self) -> List[str]:
        return self._cache.get("airlines", {}).get("domestic_airlines", [])

    @property
    def international_airlines(self) -> List[str]:
        return self._cache.get("airlines", {}).get("international_airlines", [])

    @property
    def all_airlines(self) -> List[str]:
        return self._cache.get("all_airlines", [])

    @property
    def airline_official_sites(self) -> Dict[str, str]:
        return self._cache.get("airlines", {}).get("airline_official_sites", {})

    @property
    def airline_codes(self) -> Dict[str, str]:
        return self._cache.get("airlines", {}).get("airline_codes", {})

    @property
    def aircraft_types(self) -> List[str]:
        return self._cache.get("all_aircraft", [])

    @property
    def long_haul_aircraft(self) -> List[str]:
        aircraft = self._cache.get("airlines", {}).get("aircraft_types", {})
        return aircraft.get("wide_body", [])

    @property
    def short_haul_aircraft(self) -> List[str]:
        aircraft = self._cache.get("airlines", {}).get("aircraft_types", {})
        # Exclude turboprops (ATR72) to match original SHORT_HAUL_AIRCRAFT
        regional = [a for a in aircraft.get("regional", []) if a != "ATR72"]
        return aircraft.get("narrow_body", []) + regional

    def get_raw(self, key: str) -> Any:
        """Get raw config data by key."""
        return self._cache.get(key, {})


# ── Singleton ──────────────────────────────────────────────────

_config_singleton: Optional[ConfigLoader] = None


def get_config(config_dir: str = None) -> ConfigLoader:
    """Get or create the global ConfigLoader singleton."""
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = ConfigLoader(config_dir).load()
    return _config_singleton


def reload_config() -> ConfigLoader:
    """Reload the global config singleton."""
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = ConfigLoader().load()
    else:
        _config_singleton.reload()
    return _config_singleton
