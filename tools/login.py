"""
One-time login tool for flight platforms.
Usage: python tools/login.py <platform|all|list|clean>
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# 平台登录 URL
LOGIN_URLS = {
    "ctrip":     "https://m.ctrip.com/html5/flight/swift/",
    "qunar":     "https://user.qunar.com/passport/login.jsp",
    "fliggy":    "https://login.taobao.com/",
    "tongcheng": "https://www.ly.com/",
    "airchina":  "https://www.airchina.com.cn/",
}

# 软过期时间（天）
SESSION_TTL_DAYS = 7


def list_sessions():
    """Show all saved sessions with validity status."""
    print("=== 已保存的会话 ===")
    found = False
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        found = True
        try:
            with open(f, "r", encoding="utf-8") as fh:
                s = json.load(fh)
            exp = s.get("expires_at", "N/A")
            try:
                valid = datetime.fromisoformat(exp) > datetime.now()
            except Exception:
                valid = False
            mark = "✓ 有效" if valid else "✗ 已过期"
            print(f"  {mark:8s} {f.stem:12s}  expires: {exp}  cookies: {len(s.get('cookies', []))}")
        except Exception as e:
            print(f"  ? {f.name}: {e}")
    if not found:
        print("  (no sessions yet)")


def clean_sessions():
    """Remove expired sessions."""
    removed = 0
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                s = json.load(fh)
            exp = s.get("expires_at", "")
            if exp:
                try:
                    if datetime.fromisoformat(exp) < datetime.now():
                        f.unlink()
                        removed += 1
                        print(f"  Removed: {f.name}")
                except Exception:
                    pass
        except Exception:
            pass
    print(f"Cleaned {removed} expired session(s).")


def login_one(platform: str) -> bool:
    """Open browser, navigate to platform, wait for user to log in, save cookies."""
    from playwright.sync_api import sync_playwright

    url = LOGIN_URLS.get(platform)
    if not url:
        print(f"Unknown platform: {platform}")
        return False

    print(f"\n=== Login to {platform} ===")
    print(f"  Browser opening: {url}")
    print(f"  Please scan QR / enter credentials in the browser window.")
    print(f"  Script will save cookies once you reach the home page.\n")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,  # 重要：必须有头
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                viewport={"width": 375, "height": 812},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/16.0 Mobile/15E148 Safari/604.1"
                ),
                locale="zh-CN",
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)

            # 等待用户登录成功：用户按回车确认
            print(">>> Press ENTER in this terminal once you've logged in. <<<\n")
            input()

            # 抓取 cookies
            cookies = context.cookies()
            if not cookies:
                print("  No cookies captured, login may have failed.")
                browser.close()
                return False

            now = datetime.now()
            session = {
                "platform": platform,
                "logged_in_at": now.isoformat(),
                "expires_at": (now + timedelta(days=SESSION_TTL_DAYS)).isoformat(),
                "cookies": cookies,
                "user_agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/16.0 Mobile/15E148 Safari/604.1"
                ),
                "viewport": {"width": 375, "height": 812},
            }
            # Save encrypted via SessionManager
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from core.session_manager import SessionManager
            sm = SessionManager()
            sm.save(platform, session)

            print(f"  ✓ Saved {len(cookies)} cookies (encrypted) for {platform}")
            print(f"  ✓ Expires at: {session['expires_at']}")
            browser.close()
            return True
    except ImportError:
        print("  playwright not installed. Run: pip install playwright")
        return False
    except Exception as e:
        print(f"  Login failed: {e}")
        return False


def load_session(platform: str) -> dict:
    """Load saved session, return None if not found or expired."""
    path = SESSIONS_DIR / f"{platform}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = json.load(f)
        exp_str = s.get("expires_at", "2000-01-01")
        try:
            exp = datetime.fromisoformat(exp_str)
        except Exception:
            return None
        if exp < datetime.now():
            return None
        return s
    except Exception as e:
        print(f"[{platform}] failed to load session: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python login.py <platform|all|list|clean>")
        print("Platforms:", ", ".join(LOGIN_URLS.keys()))
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "list":
        list_sessions()
    elif cmd == "clean":
        clean_sessions()
    elif cmd == "all":
        for p in LOGIN_URLS:
            login_one(p)
    elif cmd in LOGIN_URLS:
        login_one(cmd)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
