"""
Flight Monitor API — Shared Utilities

Rate limiter, auth helpers, and IP resolution shared across
all route modules. These are used by _routes.py-style modules
(not Flask Blueprints).
"""
import hashlib
import logging
import os
import time
import threading
from collections import defaultdict, deque
from flask import request, jsonify

logger = logging.getLogger(__name__)

# ── Security / rate-limit config (env-driven) ────────────────
API_KEY = os.environ.get("FLIGHT_MONITOR_API_KEY", "")
OPEN_MODE = os.environ.get("FLIGHT_MONITOR_OPEN_MODE", "").lower() in ("1", "true", "yes")
CORS_ORIGIN = os.environ.get("FLIGHT_MONITOR_CORS_ORIGIN", "")
TRUSTED_PROXIES = os.environ.get("FLIGHT_MONITOR_TRUSTED_PROXIES", "")

_VALID_CABIN = {"economy", "business", "first"}


# ── Rate Limiter ──────────────────────────────────────────────

class RateLimiter:
    """In-memory per-IP token-bucket rate limiter."""

    _MAX_IPS = 4096

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, ip, max_calls, window_s):
        now = time.time()
        with self._lock:
            bucket = self._hits[ip]
            while bucket and now - bucket[0] > window_s:
                bucket.popleft()
            if len(bucket) >= max_calls:
                return False
            bucket.append(now)
            if len(self._hits) > self._MAX_IPS:
                cutoff = now - window_s
                self._hits = {k: v for k, v in self._hits.items()
                              if v and v[-1] > cutoff}
            return True


# Global instance
rate_limiter = RateLimiter()


# ── IP Resolution ─────────────────────────────────────────────

def client_ip():
    """Client IP with optional trusted-proxy X-Forwarded-For support."""
    remote = request.remote_addr or "unknown"
    if not TRUSTED_PROXIES:
        return remote
    if TRUSTED_PROXIES != "*" and remote not in TRUSTED_PROXIES.split(","):
        return remote
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        ips = [ip.strip() for ip in xff.split(",")]
        for ip in reversed(ips):
            if ip and (TRUSTED_PROXIES == "*"
                       or ip not in TRUSTED_PROXIES.split(",")):
                return ip
    return remote


# ── API Key Auth ──────────────────────────────────────────────

def check_api_key():
    """Return error response if API key is required and invalid."""
    if not API_KEY:
        return None
    provided = request.headers.get("X-API-Key", "")
    if provided == API_KEY:
        return None
    return jsonify({"error": "invalid or missing API key"}), 401


# ── Stable Seed ───────────────────────────────────────────────

def stable_seed(*parts):
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.md5(raw.encode("utf-8")).hexdigest()[:8], 16)
