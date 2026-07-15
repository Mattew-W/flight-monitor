"""
Flight Monitor - Shared Browser Pool (v4 — Async)
Single Chromium process, per-platform context isolation.
All I/O is async — one event loop drives N concurrent searches.
"""
import asyncio
import logging
import os
import sys
import time
from typing import Optional, Dict

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

_CHROME_PATHS = []

# 1) User-provided override via env var (highest priority)
_chrome_env = os.environ.get("CHROME_PATH", "").strip()
if _chrome_env:
    _CHROME_PATHS.append(_chrome_env)

# 2) Platform-specific system paths
if sys.platform == "win32":
    _CHROME_PATHS.extend([
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ])
elif sys.platform == "darwin":
    _CHROME_PATHS.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
elif sys.platform.startswith("linux"):
    _CHROME_PATHS.extend([
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/snap/bin/chromium",
    ])

_CHROME_PATH = None
for _p in _CHROME_PATHS:
    if _p and os.path.exists(_p):
        _CHROME_PATH = _p
        break

# If no system Chrome found, Playwright will use its own bundled Chromium.
# This is normal — _start_internal() skips executable_path when _CHROME_PATH is None.

_IDLE_TIMEOUT = 180
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


class AsyncBrowserPool:
    """Async singleton browser pool with platform-isolated contexts.\n\n    Use via the module-level `get_browser_pool()` factory.\n    """

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._contexts: Dict[str, BrowserContext] = {}
        self._lock = asyncio.Lock()
        self._last_used = 0.0
        self._refcount = 0
        self._warmup_done = set()

    # ── Public API ──────────────────────────────────────────

    async def get_context(self, platform: str = "default") -> Optional[BrowserContext]:
        return await self.acquire(platform)

    async def acquire(self, platform: str = "default") -> Optional[BrowserContext]:
        if not HAS_PLAYWRIGHT:
            return None
        async with self._lock:
            now = time.time()
            if (self._browser
                    and (now - self._last_used) > _IDLE_TIMEOUT
                    and self._refcount == 0):
                logger.info("BrowserPool: idle timeout, recycling")
                await self._close_internal()
            if not self._browser:
                if not await self._start_internal():
                    return None
            if platform not in self._contexts:
                self._contexts[platform] = await self._browser.new_context(
                    viewport={"width": 375, "height": 812},
                    user_agent=_USER_AGENT,
                    locale="zh-CN",
                )
                logger.info(f"BrowserPool: isolated context for '{platform}'")
                await self._apply_session(self._contexts[platform], platform)
            self._last_used = now
            return self._contexts[platform]

    async def release(self):
        async with self._lock:
            self._refcount = max(0, self._refcount - 1)
            self._last_used = time.time()

    async def new_page(self, platform: str = "default"):
        try:
            ctx = await self.acquire(platform)
            if ctx is None:
                return None
            self._refcount += 1
            return await ctx.new_page()
        except Exception as e:
            await self.release()
            logger.warning(f"BrowserPool: new_page '{platform}' failed: {e}")
            return None

    async def close_page(self, page):
        try:
            if page:
                await page.close()
        except Exception:
            pass
        await self.release()

    async def warmup(self, url: str = "https://m.ctrip.com/html5/flight/swift/",
                     timeout_ms: int = 10000, platforms: list = None):
        if not HAS_PLAYWRIGHT:
            return False
        from .session_manager import get_session_manager
        if platforms is None:
            platforms = get_session_manager().list_platforms()
        async with self._lock:
            if not await self._start_internal():
                return False
        for plat in platforms:
            if plat in self._warmup_done:
                continue
            ctx = await self.acquire(plat)
            if ctx:
                page = await ctx.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await asyncio.sleep(2)
                    self._warmup_done.add(plat)
                except Exception:
                    pass
                finally:
                    await self.close_page(page)
        return True

    async def shutdown(self):
        async with self._lock:
            await self._close_internal()

    # ── Internal ────────────────────────────────────────────

    async def _start_internal(self) -> bool:
        if self._browser:
            return True
        try:
            self._playwright = await async_playwright().start()
            launch_kw = {"headless": True, "args": _BROWSER_ARGS}
            if _CHROME_PATH:
                launch_kw["executable_path"] = _CHROME_PATH
            self._browser = await self._playwright.chromium.launch(**launch_kw)
            logger.info("BrowserPool: Chromium started")
            return True
        except Exception as e:
            logger.error(f"BrowserPool: start failed: {e}")
            await self._close_internal()
            return False

    async def _close_internal(self):
        self._warmup_done.clear()
        for ctx in list(self._contexts.values()):
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._playwright = None

    async def _apply_session(self, ctx, platform: str):
        try:
            from .session_manager import get_session_manager
            sm = get_session_manager()
            cookies = sm.get_cookies(platform)
            if cookies:
                await ctx.add_cookies(cookies)
                logger.info(f"BrowserPool: applied {len(cookies)} cookies to '{platform}'")
        except Exception as e:
            logger.debug(f"BrowserPool: no session for '{platform}': {e}")


# ── Module-level async singleton factory ──────────────────

_pool: Optional[AsyncBrowserPool] = None
_pool_lock = asyncio.Lock()


async def get_browser_pool() -> AsyncBrowserPool:
    global _pool
    async with _pool_lock:
        if _pool is None:
            _pool = AsyncBrowserPool()
        return _pool
