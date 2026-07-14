"""
Extract real flight data from Ctrip H5 by intercepting responses during page load.
"""
import json
import re
import time
from urllib.parse import quote
from playwright.sync_api import sync_playwright

CHROME_PATH = r"C:/Program Files/Google/Chrome/Application/chrome.exe"


def main():
    api_responses = []

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

        # Intercept all responses
        def on_response(response):
            url = response.url
            if "m.ctrip.com" in url and response.status == 200:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    path = re.search(r'm\.ctrip\.com(/[^\s?#]*)', url)
                    try:
                        body = response.json()
                        api_responses.append({
                            "path": path.group(1) if path else url,
                            "url": url[:200],
                            "body": body,
                        })
                    except:
                        pass

        page.on("response", on_response)

        # Navigate to flight list page
        dep = "北京"
        arr = "上海"
        date = "2026-07-25"
        dep_enc = quote(dep)
        arr_enc = quote(arr)
        
        # Use the H5 list page URL
        url = f"https://m.ctrip.com/html5/flight/swift/list?dcity={dep_enc}&acity={arr_enc}&ddate={date}&cabin=Y_S&adult=1&child=0&infant=0"
        print(f"[+] Navigating: {url[:80]}...")
        page.goto(url, wait_until="domcontentloaded")
        
        # Wait for flight list to render
        print("[+] Waiting for flight list to render...")
        page.wait_for_timeout(15000)
        
        # Scroll and wait more
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(5000)
        
        # Check page content
        title = page.title()
        print(f"[+] Page title: {title}")
        
        # Extract text content to see what's on the page
        body_text = page.evaluate("() => document.body?.innerText?.substring(0, 1000)")
        print(f"[+] Body text preview: {body_text[:500]}")

        print(f"\n[+] Captured {len(api_responses)} API responses")
        
        # Find the one with flight data
        for resp in api_responses:
            body_str = json.dumps(resp["body"], ensure_ascii=False)
            if any(kw in body_str for kw in ["flightNo", "airlineName", "lowestOfMonth", "departureCityCode"]):
                print(f"\n[!!!] Found flight data in: {resp['path']}")
                # Parse the data field
                data = resp["body"].get("data", "")
                if data:
                    flights = json.loads(data) if isinstance(data, str) else data
                    print(f"    Total flights: {len(flights)}")
                    for i, f in enumerate(flights[:30]):
                        print(f"    [{i}] {f.get('flightNo','')} {f.get('airlineName','')} "
                              f"{f.get('departureCityCode','')}->{f.get('arrivalCityCode','')} "
                              f"¥{f.get('price','')} disc={f.get('discount','')}")
                    
                    # Save to file
                    with open("ctrip_real_flights.json", "w", encoding="utf-8") as fout:
                        json.dump(flights, fout, ensure_ascii=False, indent=2)
                    print(f"\n[+] Saved {len(flights)} flights to ctrip_real_flights.json")

        browser.close()


if __name__ == "__main__":
    main()
