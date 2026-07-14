"""
Analyze Ctrip H5 request headers to see if we can call the API directly.
"""
import json
import re
import time
from urllib.parse import quote, urlparse, parse_qs
from playwright.sync_api import sync_playwright

CHROME_PATH = r"C:/Program Files/Google/Chrome/Application/chrome.exe"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            executable_path=CHROME_PATH,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            viewport={"width": 375, "height": 812},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        )
        page = ctx.new_page()
        
        # Intercept the getLowestPriceCalendar request to see headers
        target_request = None
        
        def on_request(request):
            nonlocal target_request
            url = request.url
            if "getLowestPriceCalendar" in url and request.method == "GET":
                target_request = {
                    "url": url,
                    "method": request.method,
                    "headers": dict(request.headers),
                    "headers_lower": {k.lower(): v for k, v in request.headers.items()},
                }
                print(f"\n[!!!] Found request:")
                print(f"    Method: {request.method}")
                print(f"    URL: {url[:200]}")
                print(f"\n    Headers:")
                for k, v in target_request["headers"].items():
                    print(f"      {k}: {v}")

        page.on("request", on_request)

        # Navigate
        dep = quote("北京")
        arr = quote("上海")
        url = f"https://m.ctrip.com/html5/flight/swift/list?dcity={dep}&acity={arr}&ddate=2026-07-25&cabin=Y_S&adult=1&child=0&infant=0"
        print(f"[+] Navigating...")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(15000)

        if target_request:
            # Parse query params
            parsed = urlparse(target_request["url"])
            params = parse_qs(parsed.query)
            print(f"\n[!!!] Query params:")
            for k, v in params.items():
                print(f"      {k}: {v}")

            # Save for analysis
            with open("ctrip_request_headers.json", "w", encoding="utf-8") as f:
                json.dump(target_request, f, ensure_ascii=False, indent=2)
            print(f"\n[+] Saved to ctrip_request_headers.json")

        browser.close()


if __name__ == "__main__":
    main()
