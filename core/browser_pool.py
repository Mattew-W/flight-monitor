"""
Flight Monitor - Shared Browser Pool (v1)
Thread-safe Playwright browser lifecycle management.
Multiple data sources share a single Chromium instance.
"""
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# Chrome paths to try
_CHROME_PATHS = [
    os.environ.get("CHROME_PATH", ""),
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]
_CHROME_PATH = None
for _p in _CHROME_PATHS:
    if _p and os.path.exists(_p):
        _CHROME_PATH = _p
        break

_IDLE_TIMEOUT = 180  # close after 3 min idle
_BROWSER_ARGS = [
    "--headless=new",
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--window-size=375,812",
]
_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Mobile/15E148 Safari/604.1"
)


class BrowserPool:
    """Thread-safe singleton browser pool for all data sources."""

    _instance: Optional["BrowserPool"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._access_lock = threading.Lock()
        self._last_used = 0.0
        self._refcount = 0
        self._warmup_done = False

    # ── Public API ──────────────────────────────────────────

    def acquire(self) -> Optional[BrowserContext]:
        """Get a shared browser context. Returns None if unavailable."""
        if not HAS_PLAYWRIGHT:
            return None
        with self._access_lock:
            self._refcount += 1
            now = time.time()
            if self._browser and (now - self._last_used) > _IDLE_TIMEOUT:
                logger.info("BrowserPool: idle timeout, recycling")
                self._close_internal()
            if not self._browser:
                ok = self._start_internal()
                if not ok:
                    self._refcount -= 1
                    return None
            self._last_used = now
            return self._context

    def release(self):
        """Release context reference."""
        with self._access_lock:
            self._refcount = max(0, self._refcount - 1)
            self._last_used = time.time()

    def new_page(self):
        """Create a new page in the shared context."""
        ctx = self.acquire()
        if ctx is None:
            return None
        return ctx.new_page()

    def close_page(self, page):
        """Close a page and release ref."""
        try:
            if page:
                page.close()
        except Exception:
            pass
        self.release()

    def warmup(self, url: str = "https://m.ctrip.com/html5/flight/swift/",
               timeout_ms: int = 10000, platforms: list = None):
        """Pre-warm the browser by loading a page and applying session cookies.

        platforms: list of platform names whose saved cookies should be loaded
                   (e.g. ["ctrip", "qunar"]). Defaults to all available sessions.
        """
        if not HAS_PLAYWRIGHT:
            return False
        with self._access_lock:
            if self._warmup_done:
                return True
            ok = self._start_internal()
            if ok:
                # Apply saved sessions
                self._apply_sessions(platforms)
                page = self._context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded",
                             timeout=timeout_ms)
                    time.sleep(2)
                except Exception:
                    pass
                finally:
                    page.close()
                self._warmup_done = True
            return ok

    def _apply_sessions(self, platforms: list = None):
        """Load saved login sessions and inject cookies into the context."""
        from .session_manager import get_session_manager
        sm = get_session_manager()
        if platforms is None:
            platforms = sm.list_platforms()
        loaded = 0
        for plat in platforms:
            cookies = sm.get_cookies(plat)
            if cookies:
                try:
                    self._context.add_cookies(cookies)
                    loaded += 1
                    logger.info(f"BrowserPool: applied {len(cookies)} cookies for {plat}")
                except Exception as e:
                    logger.warning(f"BrowserPool: failed to apply {plat} cookies: {e}")
        if loaded:
            logger.info(f"BrowserPool: total {loaded} platform session(s) loaded")

    def shutdown(self):
        """Force close everything."""
        with self._access_lock:
            self._close_internal()

    # ── Internal ────────────────────────────────────────────

    def _start_internal(self) -> bool:
        if self._browser:
            return True
        try:
            self._playwright = sync_playwright().start()
            launch_kw = {"headless": True, "args": _BROWSER_ARGS}
            if _CHROME_PATH:
                launch_kw["executable_path"] = _CHROME_PATH
            self._browser = self._playwright.chromium.launch(**launch_kw)
            self._context = self._browser.new_context(
                viewport={"width": 375, "height": 812},
                user_agent=_USER_AGENT,
                locale="zh-CN",
            )
            logger.info("BrowserPool: started shared browser")
            return True
        except Exception as e:
            logger.error(f"BrowserPool: start failed: {e}")
            self._close_internal()
            return False

    def _close_internal(self):
        self._warmup_done = False
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._browser = None
        self._playwright = None


# ── Module-level singleton ──────────────────────────────────

_browser_pool: Optional[BrowserPool] = None


def get_browser_pool() -> BrowserPool:
    global _browser_pool
    if _browser_pool is None:
        _browser_pool = BrowserPool()
    return _browser_pool
