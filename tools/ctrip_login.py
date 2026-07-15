"""
Ctrip Login Helper — 手动登录携程并保存 Cookie

运行后会打开一个可视化浏览器窗口，你手动登录携程。
登录成功后按 Enter，Cookie 自动保存到 ctrip_cookies.json。
后续爬虫自动加载这些 Cookie，就能拿到完整的航班数据。

用法:
    python ctrip_login.py              # 打开浏览器登录
    python ctrip_login.py --check      # 检查 Cookie 是否有效
"""
import json
import os
import sys
import time
import logging
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ctrip_login")

COOKIE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "ctrip_cookies.json")


def login_and_save():
    """Open browser for manual login, save cookies."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("请先安装 playwright: pip install playwright && playwright install chromium")
        return False
    
    print("\n" + "=" * 55)
    print("  携程登录助手")
    print("=" * 55)
    print()
    print("即将打开浏览器窗口，请手动登录携程。")
    print("登录成功后，回到这里按 Enter 键保存 Cookie。")
    print()
    input("按 Enter 开始...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled",
                  "--window-size=1280,900"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = context.new_page()
        
        # Go to Ctrip login page
        page.goto("https://passport.ctrip.com/user/login?", wait_until="domcontentloaded")
        
        print()
        print("请在浏览器中登录携程（手机号/微信/支付宝均可）")
        print("登录成功后，回到这里按 Enter 键...")
        print()
        input()
        
        # Save cookies
        cookies = context.cookies()
        
        # Also save localStorage if available (some sites use it for tokens)
        try:
            local_storage = page.evaluate("() => JSON.stringify(window.localStorage)")
        except Exception:
            local_storage = "{}"
        
        data = {
            "cookies": cookies,
            "localStorage": json.loads(local_storage) if local_storage else {},
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        browser.close()
    
    print(f"\n✅ Cookie 已保存到: {COOKIE_FILE}")
    print(f"   包含 {len(cookies)} 个 Cookie")
    print()
    
    return True


def load_cookies():
    """Load saved cookies."""
    if not os.path.exists(COOKIE_FILE):
        return None
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("cookies", [])
    except Exception:
        return None


def check_cookies_valid():
    """Check if saved cookies are still valid by accessing Ctrip."""
    cookies = load_cookies()
    if not cookies:
        print("❌ 没有找到保存的 Cookie，请先运行 ctrip_login.py 登录")
        return False
    
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright 未安装")
        return False
    
    print(f"检查 Cookie 有效性... ({len(cookies)} cookies)")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--headless=new", "--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 375, "height": 812},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
            ),
        )
        context.add_cookies(cookies)
        page = context.new_page()
        
        # Test with flight search - watch for flightGloryList
        api_success = {}
        
        def on_response(r):
            if r.status != 200:
                return
            if "flightGloryList" in r.url:
                try:
                    d = r.json()
                    finfo = d.get("finfo", [])
                    if finfo and len(finfo) > 0:
                        api_success["flightGloryList"] = len(finfo)
                except Exception:
                    pass
            elif "getLowestPriceCalendar" in r.url:
                try:
                    d = r.json()
                    data = d.get("data", "")
                    if data:
                        flights = json.loads(data) if isinstance(data, str) else data
                        if flights:
                            api_success["getLowestPriceCalendar"] = len(flights)
                except Exception:
                    pass
        
        page.on("response", on_response)
        page.goto(
            "https://m.ctrip.com/html5/flight/swift/list?"
            "dcity=%E5%8C%97%E4%BA%AC&acity=%E4%B8%8A%E6%B5%B7"
            "&ddate=2026-08-12&cabin=Y_S&adult=1&child=0&infant=0",
            wait_until="domcontentloaded", timeout=20000
        )
        page.wait_for_timeout(5000)
        browser.close()
    
    print()
    for api, count in api_success.items():
        print(f"  ✅ {api}: {count} 条数据")
    
    if "flightGloryList" in api_success:
        print(f"\n✅ Cookie 有效！flightGloryList 能拿到 {api_success['flightGloryList']} 条航班数据！")
        return True
    elif "getLowestPriceCalendar" in api_success:
        print(f"\n⚠️  Cookie 可能已过期。能拿到日历数据（{api_success['getLowestPriceCalendar']}条），但 flightGloryList 无数据。")
        print("   建议重新登录: python ctrip_login.py")
        return False
    else:
        print("\n❌ Cookie 已失效，建议重新登录")
        return False


def main():
    parser = argparse.ArgumentParser(description="Ctrip Login Helper")
    parser.add_argument("--check", action="store_true", help="Check if saved cookies are valid")
    args = parser.parse_args()
    
    if args.check:
        check_cookies_valid()
    else:
        login_and_save()


if __name__ == "__main__":
    main()
