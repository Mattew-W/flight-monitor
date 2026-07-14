"""
Test if the Ctrip getLowestPriceCalendar API can be called directly.
This API returns real flight data (flight numbers, airlines, prices).
"""
import json
import requests


def get_client_id():
    """Get a ClientID from Ctrip's createclientid API."""
    url = "https://m.ctrip.com/restapi/soa2/10290/createclientid"
    params = {
        "systemcode": "09",
        "createtype": "3",
        "head[cid]": "",
        "head[ctok]": "",
        "head[cver]": "1.0",
        "head[lang]": "01",
        "head[sid]": "8888",
        "head[syscode]": "09",
        "head[auth]": "null",
        "head[extension][0][name]": "protocal",
        "head[extension][0][value]": "https",
        "contentType": "json",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://m.ctrip.com/html5/flight/swift/",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    data = resp.json()
    client_id = data.get("ClientID", "")
    print(f"[+] ClientID: {client_id}")
    return client_id


def get_lowest_price_calendar(client_id, dep_code, arr_code):
    """Call getLowestPriceCalendar API for a route."""
    url = "https://m.ctrip.com/restapi/soa2/19691/getLowestPriceCalendar"
    params = {
        "_fxpcqlniredt": client_id,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://m.ctrip.com/html5/flight/swift/",
        "Content-Type": "application/json",
    }
    # The API might need a POST body with route info
    payload = {
        "departureCityCode": dep_code,
        "arrivalCityCode": arr_code,
        "departureDate": "",  # empty for calendar view
        "cabin": "Y_S",
        "adult": 1,
        "child": 0,
        "infant": 0,
    }
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    print(f"[+] Response status: {resp.status_code}")
    print(f"[+] Content-Type: {resp.headers.get('content-type', '')}")
    data = resp.json()
    return data


def test_with_post(client_id, dep_code, arr_code):
    """Try POST request with route info in body."""
    url = f"https://m.ctrip.com/restapi/soa2/19691/getLowestPriceCalendar?_fxpcqlniredt={client_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://m.ctrip.com/html5/flight/swift/",
        "Content-Type": "application/json",
        "Origin": "https://m.ctrip.com",
    }
    payload = {
        "departureCityCode": dep_code,
        "arrivalCityCode": arr_code,
        "cabin": "Y_S",
        "adult": 1,
        "child": 0,
        "infant": 0,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    print(f"[+] POST status: {resp.status_code}")
    data = resp.json()
    return data


def main():
    print("=" * 60)
    print("Testing Ctrip getLowestPriceCalendar API")
    print("=" * 60)

    # Step 1: Get ClientID
    client_id = get_client_id()
    if not client_id:
        print("[-] Failed to get ClientID")
        return

    # Step 2: Try GET request
    print("\n[+] Testing GET request for BJS -> SHA...")
    data = get_lowest_price_calendar(client_id, "BJS", "SHA")
    print(f"[+] Response keys: {list(data.keys())}")
    if "data" in data:
        raw_data = data["data"]
        if isinstance(raw_data, str):
            flights = json.loads(raw_data)
        else:
            flights = raw_data
        print(f"[+] Found {len(flights)} flight entries")
        if flights:
            print(f"[+] First flight: {json.dumps(flights[0], ensure_ascii=False, indent=2)}")
    else:
        print(f"[+] Full response: {json.dumps(data, ensure_ascii=False)[:500]}")

    # Step 3: Try POST with route info
    print("\n[+] Testing POST request for BJS -> SHA...")
    data = test_with_post(client_id, "BJS", "SHA")
    print(f"[+] Response keys: {list(data.keys())}")
    if "data" in data:
        raw_data = data["data"]
        if isinstance(raw_data, str):
            flights = json.loads(raw_data)
        else:
            flights = raw_data
        print(f"[+] Found {len(flights)} flight entries")
        if flights:
            print(f"[+] First flight: {json.dumps(flights[0], ensure_ascii=False, indent=2)}")

    # Step 4: Test international route
    print("\n[+] Testing POST request for BJS -> LON (London)...")
    data = test_with_post(client_id, "BJS", "LON")
    print(f"[+] Response keys: {list(data.keys())}")
    if "data" in data:
        raw_data = data["data"]
        if isinstance(raw_data, str):
            flights = json.loads(raw_data)
        else:
            flights = raw_data
        print(f"[+] Found {len(flights)} flight entries")
        if flights:
            print(f"[+] First flight: {json.dumps(flights[0], ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    main()
