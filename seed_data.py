"""
Seed Data Collector v4 — 并行Mock + 新鲜浏览器Ctrip

改进:
  - CtripBrowserSource(fresh_per_search=True) 每次搜索新浏览器，避免限流
  - 空结果不存 DB（不浪费时间创建无数据查询）
  - 每轮 Ctrip 搜索加入可配置延迟
  - 进度条显示当前路线

用法:
    python seed_data.py                        # 并行Mock + 串行Ctrip
    python seed_data.py --mock -w 16           # 纯Mock
    python seed_data.py --ctrip-only -d 3      # 纯Ctrip，每条搜完等3s
    python seed_data.py -n 5 --ctrip-only     # Ctrip只采前5条路线
    python seed_data.py --mock-only            # 只Mock，不启动浏览器
"""
import sys
import os
import time
import random
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DB_PATH, POPULAR_ROUTES
from core.database import Database
from core.models import SearchQuery
from datasources import MockDataSource, CtripBrowserSource

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("datasources.ctrip_browser_source").setLevel(logging.INFO)
logger = logging.getLogger("seed_data")

_p_lock = threading.Lock()
_done = 0
_total = 0
_t0 = 0
_current_route = ""


def _tick(n=1, route=""):
    global _done, _current_route
    with _p_lock:
        _done += n
        if route:
            _current_route = route
        e = time.time() - _t0
        r = _done / e * 60 if e > 0 else 0
        msg = f"\r  [{_done}/{_total}] {e:.0f}s | {r:.0f}/min"
        if _current_route:
            msg += f" | {_current_route}"
        print(msg, end="")


def gen_mock_batch(routes, mock_src, db_path, workers=16):
    """Parallel: generate Mock data for all routes."""
    tasks = []
    for route in routes:
        dep = route["departure"]
        dst = route["destination"]
        lbl = route.get("label", "")
        for tag, delta in [("near", 30), ("far", 100)]:
            tasks.append((dep, dst, lbl, tag, delta))

    def _do(task):
        dep, dst, lbl, tag, delta = task
        db = Database(db_path)
        fut = (datetime.now() + timedelta(days=delta)).strftime("%Y-%m-%d")
        q = SearchQuery(
            departure=dep, destination=dst, departure_date=fut,
            cabin_class="economy", trip_type="oneway",
            is_monitoring=False,
            label=f"{lbl}({tag})" if lbl else f"{dep}->{dst}",
        )
        qid = db.add_query(q)
        q.id = qid
        prices = []
        try:
            prices = mock_src.search_flights(q)
        except Exception:
            pass
        if prices:
            db.add_price_records(prices)
        db.close()
        _tick()
        return len(prices)

    total = 0
    w = min(len(tasks), workers)
    with ThreadPoolExecutor(max_workers=w) as ex:
        fs = {ex.submit(_do, t): t for t in tasks}
        for f in as_completed(fs):
            try:
                total += f.result()
            except Exception:
                pass
    return total


def collect_ctrip(routes, ctrip_src, db_path, delay_sec=2.0):
    """Serial: Ctrip browser scraping with fresh browser per search."""
    db = Database(db_path)
    total = 0
    skipped = 0
    empty_streak = 0  # consecutive empty results
    empty_abort = 5   # abort after this many empty in a row
    total_searches = len(routes) * 2  # near + far

    for route in routes:
        dep = route["departure"]
        dst = route["destination"]
        lbl = route.get("label", "")

        for tag, delta in [("near", 30), ("far", 100)]:
            # If IP is rate-limited (N consecutive empties), stop early
            if empty_streak >= empty_abort:
                print(f"\n  [Ctrip] Aborted: {empty_streak} consecutive empty results "
                      f"(IP rate-limited). Remaining searches skipped.")
                db.close()
                return total

            fut = (datetime.now() + timedelta(days=delta)).strftime("%Y-%m-%d")

            q = SearchQuery(
                departure=dep, destination=dst, departure_date=fut,
                cabin_class="economy", trip_type="oneway",
                is_monitoring=False,
                label=f"{lbl}({tag})" if lbl else f"{dep}->{dst}",
            )
            prices = []
            try:
                prices = ctrip_src.search_flights(q)
            except Exception as e:
                logger.warning(f"Ctrip {dep}->{dst}: {e}")

            if prices:
                empty_streak = 0  # reset
                qid = db.add_query(q)
                q.id = qid
                for p in prices:
                    p.query_id = qid
                db.add_price_records(prices)
                total += len(prices)
                _tick(n=1, route=f"{dep}->{dst} ({len(prices)})")
            else:
                skipped += 1
                empty_streak += 1
                _tick(n=1, route=f"{dep}->{dst} (0)")

            if delay_sec > 0:
                time.sleep(delay_sec + random.uniform(0, 2.0))

    db.close()
    print(f"\n  Ctrip: {total} prices from {total_searches-skipped}/{total_searches} searches "
          f"({skipped} empty)")
    return total


def main():
    import argparse
    p = argparse.ArgumentParser(
        description="Seed Data Collector v4 — fresh browser + Mock")
    p.add_argument("--mock-only", action="store_true",
                   help="Mock only (no browser)")
    p.add_argument("--ctrip-only", action="store_true",
                   help="Ctrip only (no mock)")
    p.add_argument("--mock", action="store_true",
                   help="Enable Mock phase (alias for --mock-only)")
    p.add_argument("-n", "--limit", type=int, default=0,
                   help="Only process first N routes")
    p.add_argument("-w", "--workers", type=int, default=16,
                   help="Mock worker threads")
    p.add_argument("-d", "--delay", type=float, default=2.0,
                   help="Delay (sec) between Ctrip searches")
    args = p.parse_args()

    routes = POPULAR_ROUTES[:args.limit] if args.limit else POPULAR_ROUTES
    mock_only = args.mock_only or args.mock
    ctrip_only = args.ctrip_only

    global _total, _t0
    total_routes = len(routes) * 2  # near + far
    _total = total_routes if ctrip_only or mock_only else total_routes * 2

    mock_src = MockDataSource()
    ctrip_src = None
    use_ctrip = not mock_only

    if use_ctrip:
        try:
            # fresh_per_search=True: each search creates a new browser
            ctrip_src = CtripBrowserSource(fresh_per_search=True)
            if not ctrip_src.is_available():
                ctrip_src = None
                print("  [Ctrip] Playwright not installed, skipping")
        except Exception as e:
            print(f"  [Ctrip] init failed: {e}")

    print(f"\n{'='*55}")
    print(f"  Seed v4 | Routes: {len(routes)} -> {total_routes} searches")
    print(f"  Mock: {'yes' if not ctrip_only else 'no'}"
          f" ({args.workers} workers)")
    print(f"  Ctrip: {'yes (fresh browser, delay={:.1f}s)'.format(args.delay) if ctrip_src else 'no'}")
    print(f"{'='*55}\n")

    _t0 = time.time()
    total_prices = 0

    # Phase 1: Mock data in parallel (skip if ctrip-only)
    if not ctrip_only:
        print("  [Mock]  Generating mock data (parallel)...")
        total_prices += gen_mock_batch(routes, mock_src, DB_PATH,
                                       workers=args.workers)

    # Phase 2: Ctrip data sequentially (fresh browser per search)
    if ctrip_src and not mock_only:
        print("\n  [Ctrip] Scraping with fresh browser per search...")
        print(f"  [Ctrip] Delay between searches: ~{args.delay:.1f}s "
              f"(est. total: {total_routes * (args.delay + 25) / 60:.0f} min)\n")
        _total = total_routes
        _done = 0
        total_prices += collect_ctrip(routes, ctrip_src, DB_PATH,
                                      delay_sec=args.delay)

    elapsed = time.time() - _t0
    print(f"\n{'='*55}")
    print(f"  Done: {total_prices} prices | {elapsed:.0f}s "
          f"({elapsed/60:.1f} min)")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
