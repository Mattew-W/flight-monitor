"""
Flight Monitor - Configuration
================================
Runtime settings (DB, Flask, SMTP, etc.) remain here.
Data definitions (platforms, cities, routes, airlines) are loaded from
JSON files via config.loader.ConfigLoader (S3 refactor).
"""
import os
from config.loader import get_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Database
DB_PATH = os.path.join(BASE_DIR, "flight_monitor.db")

# Flask
HOST = "127.0.0.1"
PORT = 5566
DEBUG = False

# Monitor
MONITOR_INTERVAL_SECONDS = 300  # 5 minutes default polling interval

# Notification
# Email settings (leave empty to disable; prefer env vars: SMTP_HOST, SMTP_PASS, etc.)
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

# Server Chan (WeChat push) - https://sct.ftqq.com/
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")

# Feishu webhook
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")

# ==============================================================
# Data Sources
# ==============================================================

# Which data sources are enabled
# mock = always works, covers all routes + 27 platforms (PRIMARY)
# ctrip_browser = real Ctrip data, needs fresh browser + proxy to beat rate-limit
# skyscanner = Skyscanner browse API (may be blocked in China)
# amadeus = Amadeus API (free 2k/mo, needs key, may be blocked)
# multi: qunar, fliggy, tongcheng, airchina (all need browser)
ENABLED_SOURCES = ["mock", "bing", "ctrip_browser", "ctrip", "skyscanner"]

# ── Source Priority (lower = tried first) ────────────────────
SOURCE_PRIORITY = {
    "ctrip_browser": 1,
    "ctrip": 2,
    "skyscanner": 3,
    "bing": 4,
    "mock": 99,
}

# ── Circuit Breaker Config ───────────────────────────────────
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3        # consecutive failures before opening
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 600       # seconds before testing recovery (10 min)
CIRCUIT_BREAKER_SUCCESS_THRESHOLD = 1        # successes in half_open to close

# Ctrip API
CTRIP_API_URL = "https://flights.ctrip.com/itinerary/api/12808/lowestPrice"
CTRIP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://flights.ctrip.com/",
    "Content-Type": "application/json",
}

# Ctrip Browser Scraper — anti-bot settings
CTRIP_FRESH_PER_SEARCH = True   # True = new browser per search (avoids rate limit)
CTRIP_PROXY = os.environ.get("CTRIP_PROXY", "")  # e.g. "http://user:pass@ip:port"

# ==============================================================
# S3: Data loaded from JSON via ConfigLoader
# ==============================================================

_cfg = get_config()

# ── Purchase Platforms ────────────────────────────────────────
PURCHASE_PLATFORMS = _cfg.platforms

# ── City Codes & Groups ──────────────────────────────────────
CITY_CODES = _cfg.city_codes
CITY_GROUPS = _cfg.city_groups
CITY_TO_REGION = _cfg.city_to_region

# ── Airlines ─────────────────────────────────────────────────
DOMESTIC_AIRLINES = _cfg.domestic_airlines
INTERNATIONAL_AIRLINES = _cfg.international_airlines
AIRLINES = _cfg.all_airlines
AIRLINE_OFFICIAL_SITES = _cfg.airline_official_sites
AIRLINE_CODES_EXTRA = _cfg.airline_codes

# ── Aircraft Types ───────────────────────────────────────────
AIRCRAFT_TYPES = _cfg.aircraft_types
LONG_HAUL_AIRCRAFT = _cfg.long_haul_aircraft
SHORT_HAUL_AIRCRAFT = _cfg.short_haul_aircraft

# ── Popular Routes ───────────────────────────────────────────
POPULAR_ROUTES = _cfg.popular_routes

# ── Route-Airline Mapping ────────────────────────────────────
# JSON uses string keys ("中国大陆-日韩"); code expects tuple keys (("中国大陆", "日韩"))
_ROUTE_AIRLINES_RAW = _cfg.route_airlines
ROUTE_AIRLINES: dict[tuple[str, str], list[str]] = {}
for _key, _airlines in _ROUTE_AIRLINES_RAW.items():
    _parts = _key.split("-", 1)
    if len(_parts) == 2:
        ROUTE_AIRLINES[tuple(_parts)] = _airlines
    else:
        ROUTE_AIRLINES[(_key,)] = _airlines
