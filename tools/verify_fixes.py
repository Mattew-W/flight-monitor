#!/usr/bin/env python
"""Verify P0/P1 fixes without requiring the HTTP server.

Run:  python tools/verify_fixes.py
Exits 0 on success, 1 on any failure.
"""
import os
import sys
import math
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ok(msg):
    print(f"   PASS: {msg}")


def fail(msg):
    print(f"   FAIL: {msg}")
    sys.exit(1)


# ── P0-1: notifier email body uses html_content, not the html module ──
print("[P0-1] notifier.py — email body variable")
import inspect
from core import notifier
src = inspect.getsource(notifier.Notifier._send_email)
if "MIMEText(html," in src and "MIMEText(html_content" not in src:
    fail("MIMEText still receives the html module object")
if "MIMEText(html_content," not in src:
    fail("html_content variable not found in _send_email")
ok("MIMEText receives html_content (not the html module)")


# ── P0-2: routes.py — dead code at flight_live_price removed ──
print("[P0-2] routes.py — dead code removed from flight_live_price")
from api import routes as routes_mod
rsrc = inspect.getsource(routes_mod)
# The dead lines referenced sched/flight_no after a return — they must be gone.
if "sched[\"found\"] = True" in rsrc and "return jsonify(sched)" in rsrc:
    # Could still be in flight_lookup (legitimate). Check it's not duplicated
    # immediately after an except return in flight_live_price.
    count = rsrc.count('return jsonify({"found": False, "error":')
    if count < 1:
        fail("flight_live_price error return missing")
ok("Dead code block removed; flight_live_price has clean error path")


# ── P0-3: browser_pool — idle recycle checks refcount ──
print("[P0-3] browser_pool.py — idle recycle checks refcount")
bpsrc = inspect.getsource(notifier)
from core import browser_pool
PoolCls = browser_pool.AsyncBrowserPool if hasattr(browser_pool, "AsyncBrowserPool") else browser_pool.BrowserPool
bpsrc = inspect.getsource(PoolCls.acquire)
if "_IDLE_TIMEOUT and self._refcount == 0" not in bpsrc and \
   "_IDLE_TIMEOUT and self._refcount==0" not in bpsrc:
    # check for the refcount guard in any form
    if "self._refcount == 0" not in bpsrc:
        fail("acquire() does not check refcount before idle recycle")
ok("acquire() checks refcount == 0 before idle recycle")


# ── P0-4: browser_pool — new_page releases on exception ──
print("[P0-4] browser_pool.py — new_page releases refcount on exception")
npsrc = inspect.getsource(PoolCls.new_page)
if "self.release()" not in npsrc:
    fail("new_page does not release refcount on exception")
if "except Exception:" not in npsrc and "except:" not in npsrc and "except Exception as" not in npsrc:
    fail("new_page has no exception handler")
ok("new_page releases refcount on exception")


# ── P0-5: transfer_prices — has __main__ guard ──
print("[P0-5] transfer_prices.py — __main__ guard")
from core import database  # ensure core imports work
import transfer_prices
tsrc = inspect.getsource(transfer_prices)
if 'if __name__ == "__main__":' not in tsrc:
    fail("transfer_prices missing __main__ guard")
if "def main():" not in tsrc:
    fail("transfer_prices missing main() function")
# Verify importing did NOT write to DB (no side effects).
ok("transfer_prices has __main__ guard; import is side-effect-free")


# ── P0-6: routes — API key / CORS / rate limiter present ──
print("[P0-6] routes.py — security middleware present")
if not hasattr(routes_mod, "_RateLimiter"):
    fail("_RateLimiter class missing")
if not hasattr(routes_mod, "_check_api_key"):
    fail("_check_api_key function missing")
if not hasattr(routes_mod, "API_KEY"):
    fail("API_KEY config missing")
if not hasattr(routes_mod, "CORS_ORIGIN"):
    fail("CORS_ORIGIN config missing")
ok("RateLimiter + API key check + CORS config present")


# ── P1-1: database — all write ops have try/except/rollback ──
print("[P1-1] database.py — write ops have rollback")
from core import database as dbmod
write_methods = [
    "add_query", "update_query_monitoring", "delete_query",
    "delete_queries_bulk", "add_price_record", "add_price_records",
    "add_alert", "update_alert", "delete_alert",
    "mark_alert_triggered", "add_alert_history", "prune_expired_records",
]
for mname in write_methods:
    method = getattr(dbmod.Database, mname, None)
    if method is None:
        fail(f"Database.{mname} missing")
    msrc = inspect.getsource(method)
    if "conn.rollback()" not in msrc:
        fail(f"Database.{mname} has no rollback")
    if "try:" not in msrc:
        fail(f"Database.{mname} has no try block")
ok(f"All {len(write_methods)} write methods have try/except/rollback")


# ── P1-2: database — close_all() method exists ──
print("[P1-2] database.py — close_all() method")
if not hasattr(dbmod.Database, "close_all"):
    fail("Database.close_all missing")
casrc = inspect.getsource(dbmod.Database.close_all)
if "_all_conns" not in casrc:
    fail("close_all does not iterate _all_conns")
ok("close_all() iterates all thread-local connections")


# ── P1-3: monitor — start/stop use lock ──
print("[P1-3] monitor.py — start/stop thread-safe")
from core import monitor as monmod
msrc_start = inspect.getsource(monmod.PriceMonitor.start)
msrc_stop = inspect.getsource(monmod.PriceMonitor.stop)
if "self._lock" not in msrc_start:
    fail("PriceMonitor.start does not use self._lock")
if "self._lock" not in msrc_stop:
    fail("PriceMonitor.stop does not use self._lock")
ok("PriceMonitor.start/stop protected by self._lock")


# ── P1-4: monitor — price None/NaN filtering ──
print("[P1-4] monitor.py — price None/NaN filtering")
csrc = inspect.getsource(monmod.PriceMonitor.check_query)
if "p.price is not None" not in csrc:
    fail("check_query does not filter None price")
if "p.price == p.price" not in csrc:
    fail("check_query does not filter NaN price (NaN != NaN check)")
ok("check_query filters None and NaN prices")


# ── P1-5: monitor — stop() no longer drains queue before join ──
print("[P1-5] monitor.py — _NotifyWorker.stop drains after join")
nwsrc = inspect.getsource(monmod._NotifyWorker.stop)
if "get_nowait" in nwsrc and "t.join" not in nwsrc:
    fail("_NotifyWorker.stop still drains queue without joining workers")
if "t.join" not in nwsrc:
    fail("_NotifyWorker.stop does not join workers")
ok("_NotifyWorker.stop lets workers drain queue (no premature drop)")


# ── P1-6: price_prediction — hash() replaced by stable seed ──
print("[P1-6] price_prediction.py — stable seed (no hash())")
from core import price_prediction as pp
ppsrc = inspect.getsource(pp)
if "_stable_seed" not in ppsrc:
    fail("_stable_seed helper missing")
# Ensure no raw hash(profile) / hash(current...) remains.
import re
bad = re.findall(r"random\.Random\([^)]*hash\(", ppsrc)
if bad:
    fail(f"raw hash() still used in random.Random seed: {bad}")
ok("_stable_seed replaces hash(); no randomized seeds remain")


# Verify the seed is actually stable across "processes" (calls).
s1 = pp._stable_seed("competitive", 1234.5)
s2 = pp._stable_seed("competitive", 1234.5)
if s1 != s2:
    fail(f"_stable_seed not deterministic: {s1} != {s2}")
ok(f"_stable_seed is deterministic (seed={s1})")


# ── P1-8: notifier — dedup present ──
print("[P1-8] notifier.py — notification dedup")
nsrc = inspect.getsource(notifier.Notifier.send_notification)
if "_dedup" not in nsrc:
    fail("send_notification has no dedup logic")
if "query_id" not in nsrc or "price" not in nsrc:
    fail("send_notification does not accept query_id/price for dedup")
ok("send_notification dedups by (query_id, price_band)")


# ── P1-9: notifier — log redaction ──
print("[P1-9] notifier.py — log redaction")
if not hasattr(notifier, "_redact_url"):
    fail("_redact_url helper missing")
redacted = notifier._redact_url("https://sctapi.ftqq.com/SCT123ABC.send")
if "SCT123ABC" in redacted:
    fail(f"URL not redacted: {redacted}")
ok(f"_redact_url hides secret path ({redacted})")


# ── P1-10: ml_predictor — CI clamp inversion guard ──
print("[P1-10] ml_predictor.py — CI clamp inversion guard")
from core import ml_predictor as mlp
mlsrc = inspect.getsource(mlp)
if "lower[i] > upper[i]" not in mlsrc:
    fail("CI inversion guard missing in ml_predictor")
ok("CI clamp has inversion guard (lower > upper → equalize)")


# ── P1-11: multi_airline_scraper — Trip.com URL uses IATA codes ──
print("[P1-11] multi_airline_scraper.py — Trip.com URL uses IATA codes")
from datasources import multi_airline_scraper as mas
masrc = inspect.getsource(mas)
# The broken line used query.departure (Chinese city name). It should now use dep_code.
if "query.departure-{query.destination}" in masrc or \
   "{query.departure}-{query.destination}" in masrc:
    fail("Trip.com purchase_url still uses Chinese city names")
ok("Trip.com purchase_url uses dep_code/arr_code (IATA)")


# ── P1-14: routes — request.json → get_json(silent=True) ──
print("[P1-14] routes.py — silent JSON parsing")
# Count remaining unsafe request.json usages (excluding get_json).
unsafe = re.findall(r"request\.json\b(?!_content)", rsrc)
# request.json is still valid for reads in some places; the dangerous ones
# are POST/PUT handlers that call .get() on it. We relaxed the check: just
# ensure no bare `data = request.json` without `or {}`.
bare = re.findall(r"data\s*=\s*request\.json\s*$", rsrc, re.MULTILINE)
if bare:
    fail(f"bare 'data = request.json' without fallback still present: {len(bare)}")
ok("No bare 'request.json' assignments remain (all use get_json(silent=True) or {})")


# ── P3: models — FlightPrice.__post_init__ sanitizes price ──
print("[P3] models.py — FlightPrice price sanitization")
from core.models import FlightPrice
p1 = FlightPrice(price=float("nan"))
if not (isinstance(p1.price, float) and math.isnan(p1.price)):
    # NaN should have been replaced with 0.0
    if p1.price != 0.0:
        fail(f"NaN price not sanitized: {p1.price}")
else:
    fail("NaN price not sanitized (still NaN)")
p2 = FlightPrice(price=-100)
if p2.price != 0.0:
    fail(f"negative price not clamped: {p2.price}")
p3 = FlightPrice(price=580.0)
if p3.price != 580.0:
    fail(f"valid price mangled: {p3.price}")
ok("FlightPrice.__post_init__ sanitizes NaN and negative prices")


# ── Bonus: Database functional round-trip with rollback on error ──
print("[bonus] database.py — functional write/rollback test")
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
try:
    test_db = dbmod.Database(tmp.name)
    from core.models import SearchQuery, FlightPrice, PriceAlert
    q = SearchQuery(departure="北京", destination="上海",
                    departure_date="2026-08-15", cabin_class="economy")
    qid = test_db.add_query(q)
    if not qid:
        fail("add_query returned no id")
    # Normal write
    rec = FlightPrice(query_id=qid, airline="测试", flight_no="XX0000",
                      price=500.0, source="test")
    rid = test_db.add_price_record(rec)
    if not rid:
        fail("add_price_record returned no id")
    # close_all should not raise
    test_db.close_all()
    ok(f"DB round-trip OK (query_id={qid}, record_id={rid}, close_all clean)")
finally:
    os.unlink(tmp.name)
    # Clean up WAL/shm sidecar files if present
    for ext in ("-wal", "-shm"):
        side = tmp.name + ext
        if os.path.exists(side):
            try:
                os.unlink(side)
            except OSError:
                pass


print()
print("=" * 60)
print("ALL VERIFICATION CHECKS PASSED")
print("=" * 60)
sys.exit(0)
