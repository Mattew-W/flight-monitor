"""
Intercept Ctrip H5 mobile flight search API.
Captures response bodies to find which endpoint returns actual flight data.
"""
import json
import re
import time
from urllib.parse import quote
from playwright.sync_api import sync_playwright

CHROME_PATH = r"C:/Program Files/Google/Chrome/Application/chrome.exe"

# Route to search
DEP = "北京"
ARR = "上海"
DATE = "2026-07-25"


def main():
    api_calls = []

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

        # Intercept responses AND their bodies
        def on_response(response):
            url = response.url
            if "m.ctrip.com" in url and response.status == 200:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    path = re.search(r'm\.ctrip\.com(/[^\s?#]*)', url)
                    entry = {
                        "url": url,
                        "path": path.group(1) if path else url,
                        "status": response.status,
                        "time": time.time(),
                    }
                    # Try to get body
                    try:
                        body = response.json()
                        # Check if this looks like flight data (has airline, price, flight_no etc)
                        body_str = json.dumps(body, ensure_ascii=False)
                        has_flight = any(kw in body_str for kw in ["airlineName", "flightNo", "price", "departureTime", "arrivalTime"])
                        entry["has_flight_data"] = has_flight
                        entry["body_preview"] = body_str[:500]
                        if has_flight:
                            entry["body"] = body
                    except Exception:
                        pass
                    api_calls.append(entry)

        page.on("response", on_response)

        # Test 1: Navigate with URL-encoded Chinese city names
        dep_encoded = quote(DEP)
        arr_encoded = quote(ARR)
        search_url = f"https://m.ctrip.com/html5/flight/swift/list?dcity={dep_encoded}&acity={arr_encoded}&ddate={DATE}&cabin=Y_S&adult=1&child=0&infant=0"
        print(f"[+] Test 1: Navigating with encoded Chinese: {search_url}")
        page.goto(search_url, wait_until="domcontentloaded")
        
        # Wait for results
        print("[+] Waiting 12s for flight results...")
        page.wait_for_timeout(12000)
        
        # Scroll to bottom to trigger lazy loading
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

        # Take screenshot
        page.screenshot(path="ctrip_test1.png", full_page=False)

        # Test 2: Navigate to homepage first, then fill in search form
        print("\n[+] Test 2: Navigating to homepage then filling search form...")
        page.goto("https://m.ctrip.com/html5/flight/swift/", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        
        # Try to interact with the form
        try:
            # Find departure city input and click it
            dep_input = page.locator("input[placeholder*='出发'], input[placeholder*='出发城市']").first
            if dep_input.is_visible():
                print("[+] Found departure input, clicking...")
                dep_input.click()
                page.wait_for_timeout(1000)
                dep_input.fill(DEP)
                page.wait_for_timeout(1000)
        except Exception as e:
            print(f"[!] Dep input error: {e}")

        page.screenshot(path="ctrip_test2.png", full_page=False)
        page.wait_for_timeout(5000)

        # Print results
        print(f"\n[+] Captured {len(api_calls)} Ctrip API calls:")
        flight_apis = []
        for i, call in enumerate(api_calls):
            has_flight = call.get("has_flight_data", False)
            marker = " <<< FLIGHT DATA!" if has_flight else ""
            print(f"  [{i}] {call['path']}{marker}")
            if has_flight:
                flight_apis.append(call)
                print(f"      Body preview: {call.get('body_preview', '')[:200]}")

        if flight_apis:
            print(f"\n[+] Found {len(flight_apis)} APIs with flight data!")
            for api in flight_apis:
                print(f"    Path: {api['path']}")
                print(f"    URL: {api['url'][:150]}")
                if 'body' in api:
                    print(f"    Full body saved")
        else:
            print("\n[!] No APIs with flight data found yet. Listing all paths:")
            for i, call in enumerate(api_calls):
                print(f"    [{i}] {call['path']}")

        browser.close()

    # Save all API calls including any flight data
    with open("ctrip_api_calls_full.json", "w", encoding="utf-8") as f:
        json.dump(api_calls, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[+] Full API data saved to ctrip_api_calls_full.json")


if __name__ == "__main__":
    main()
