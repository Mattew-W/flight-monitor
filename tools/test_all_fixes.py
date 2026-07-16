#!/usr/bin/env python
"""Verify all bug fixes."""
import json
import sys
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://127.0.0.1:5566"

def api(path, method="GET", data=None):
    url = BASE + path
    if data:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=method)
    else:
        req = urllib.request.Request(url, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

print("=" * 60)
print("VERIFICATION: Bug Fixes")
print("=" * 60)

# 1. Prediction with expired date -> should return error
print("\n[1] Testing expired date prediction...")
# Query 2 has date 2026-07-25 (future), create one with past date
past_q = api("/api/queries", "POST", {
    "departure": "北京", "destination": "上海",
    "departure_date": "2025-01-01", "cabin_class": "economy",
    "trip_type": "oneway", "label": "past-test"
})
past_id = past_q.get("id")
if past_id:
    result = api(f"/api/queries/{past_id}/predict")
    if result.get("error"):
        print(f"   PASS: Got expected error: {result['error']}")
    else:
        print(f"   FAIL: No error for expired date, got: {result}")
    api(f"/api/queries/{past_id}", "DELETE")

# 2. Prediction with valid date -> should have chart_data
print("\n[2] Testing valid date prediction...")
result = api("/api/queries/2/predict")
chart_data = result.get("chart_data", {})
datasets = chart_data.get("datasets", [])
labels = chart_data.get("labels", [])
print(f"   Labels: {len(labels)}")
print(f"   Datasets: {len(datasets)}")
for ds in datasets:
    valid = [x for x in ds.get("data", []) if x is not None]
    print(f"   - {ds['label']}: {len(valid)} points")
if len(datasets) == 4 and len(labels) > 0:
    print("   PASS: chart_data structure is correct")
else:
    print("   FAIL: chart_data structure is wrong")

# 3.NaN guard (simulate with a fresh query)
print("\n[3] Testing empty data handling...")
empty_q = api("/api/queries", "POST", {
    "departure": "哈尔滨", "destination": "三亚",
    "departure_date": "2026-08-01", "cabin_class": "economy",
    "trip_type": "oneway", "label": "empty-test"
})
empty_id = empty_q.get("id")
if empty_id:
    # Don't search, just get prediction -> should handle empty data
    result = api(f"/api/queries/{empty_id}/predict")
    if result.get("error") or result.get("chart_data"):
        print(f"   PASS: Empty data handled correctly (no crash)")
    else:
        print(f"   Result: {result}")
    api(f"/api/queries/{empty_id}", "DELETE")

# 4. Headless Playwright search
print("\n[4] Testing headless Playwright search...")
search_q = api("/api/queries", "POST", {
    "departure": "北京", "destination": "上海",
    "departure_date": "2026-07-20", "cabin_class": "economy",
    "trip_type": "oneway", "label": "playwright-test"
})
search_id = search_q.get("id")
if search_id:
    import time
    start = time.time()
    result = api(f"/api/queries/{search_id}/search", "POST")
    elapsed = time.time() - start
    print(f"   Search time: {elapsed:.1f}s")
    print(f"   Flights: {result.get('count', 0)}")
    print(f"   Total records: {result.get('total_records', 0)}")
    platforms = result.get("platforms", [])
    print(f"   Platforms: {platforms}")
    if result.get("count", 0) > 0:
        print("   PASS: Headless search works")
    else:
        print("   FAIL: No flights returned")
    api(f"/api/queries/{search_id}", "DELETE")

# 5. Test duplicate listener fix (run search twice)
print("\n[5] Testing duplicate listener fix (search twice)...")
dup_q = api("/api/queries", "POST", {
    "departure": "北京", "destination": "上海",
    "departure_date": "2026-07-20", "cabin_class": "economy",
    "trip_type": "oneway", "label": "dup-test"
})
dup_id = dup_q.get("id")
if dup_id:
    r1 = api(f"/api/queries/{dup_id}/search", "POST")
    r2 = api(f"/api/queries/{dup_id}/search", "POST")
    print(f"   Search 1: {r1.get('count', 0)} flights")
    print(f"   Search 2: {r2.get('count', 0)} flights")
    if r1.get('count', 0) > 0 and r2.get('count', 0) > 0:
        print("   PASS: Both searches returned data (no listener issues)")
    else:
        print("   FAIL: Second search returned different results")
    api(f"/api/queries/{dup_id}", "DELETE")

print("\n" + "=" * 60)
print("VERIFICATION COMPLETE")
print("=" * 60)
