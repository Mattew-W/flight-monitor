"""
Flight Schedule Auto-Builder — 从已有价格数据自动构建航班时刻表

不需要额外爬取 schedule 页面。每次搜索/监控时，ctrip_browser + mock 数据源
已经返回了航班号、航司、时间、机场等信息。本模块从数据库中提取并构建时刻表。

用法:
    python schedule_from_prices.py            # 从数据库导出当前时刻表
    python schedule_from_prices.py --export   # 导出为 flight_schedules_auto.json
"""
import json
import os
import sys
import logging
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import Database
from config import DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("schedule_builder")


def build_schedule_from_db(db: Database) -> dict:
    """Extract flight schedule data from existing price records.
    
    Deduplicates by (route_key, flight_no) and builds the most complete
    record from all available price data points.
    
    Returns: {route_key: [flight_dict, ...]}
    """
    from collections import defaultdict
    
    logger.info("Querying price records for schedule data...")
    
    # Get all unique flights from price_records
    conn = db._get_conn()
    try:
        rows = conn.execute("""
            SELECT DISTINCT
                airline, flight_no, aircraft,
                departure_time, arrival_time,
                departure_airport, arrival_airport,
                duration, stops, source
            FROM price_records
            WHERE flight_no != '' AND airline != ''
            ORDER BY airline, flight_no
        """).fetchall()
    finally:
        conn.close()
    
    # Also get route info from search_queries
    conn = db._get_conn()
    try:
        query_rows = conn.execute("""
            SELECT DISTINCT departure, destination
            FROM search_queries
        """).fetchall()
    finally:
        conn.close()
    
    # Build route code map
    from config import CITY_CODES
    route_codes = {}
    for row in query_rows:
        dep_code = CITY_CODES.get(row["departure"], "")
        arr_code = CITY_CODES.get(row["destination"], "")
        if dep_code and arr_code:
            route_codes[(row["departure"], row["destination"])] = (dep_code, arr_code)
    
    # Group flights by route
    schedules = defaultdict(list)
    seen = {}
    
    for row in rows:
        flight_no = row["flight_no"]
        airline = row["airline"]
        
        # Guess route from airport names using known routes
        # If we can't determine the route, group by flight_no only
        unique_key = f"{airline}_{flight_no}"
        if unique_key in seen:
            # Keep the record with more complete data
            existing = seen[unique_key]
            new_data = dict(row)
            # Merge: prefer non-empty values
            for key in ["departure_time", "arrival_time", "aircraft",
                       "departure_airport", "arrival_airport", "duration"]:
                if new_data.get(key) and not existing.get(key):
                    existing[key] = new_data[key]
        else:
            seen[unique_key] = dict(row)
    
    logger.info(f"Extracted {len(seen)} unique flights from price data")
    
    # Convert to route-based format
    result = {}
    for flight in seen.values():
        flight_no = flight["flight_no"]
        result.setdefault("_all", []).append({
            "flightNo": flight_no,
            "airline": flight["airline"],
            "airlineCode": flight_no[:2] if len(flight_no) >= 2 else "",
            "aircraft": flight.get("aircraft", ""),
            "departTime": flight.get("departure_time", ""),
            "arriveTime": flight.get("arrival_time", ""),
            "departPort": flight.get("departure_airport", ""),
            "arrivePort": flight.get("arrival_airport", ""),
            "duration": flight.get("duration", ""),
            "stops": flight.get("stops", 0),
            "source": flight.get("source", ""),
        })
    
    return result


def merge_with_static(auto_data: dict, static_path: str) -> dict:
    """Merge auto-generated schedule with existing static schedule data."""
    static_data = {}
    if os.path.exists(static_path):
        try:
            mod = {}
            with open(static_path, "r", encoding="utf-8") as f:
                exec(f.read(), mod)
            static_data = mod.get("REAL_FLIGHT_SCHEDULES", {})
        except Exception as e:
            logger.warning(f"Could not read static schedule: {e}")
    
    merged = dict(static_data)
    
    for flight in auto_data.get("_all", []):
        fn = flight["flightNo"]
        if fn not in merged:
            merged[fn] = {
                "dep": flight.get("departTime", ""),
                "arr": flight.get("arriveTime", ""),
                "aircraft": flight.get("aircraft", ""),
                "airline": flight.get("airline", ""),
                "dep_port": flight.get("departPort", ""),
                "arr_port": flight.get("arrivePort", ""),
                "duration": flight.get("duration", ""),
            }
    
    return merged


def main():
    parser = argparse.ArgumentParser(description="Build flight schedule from price data")
    parser.add_argument("--export", action="store_true", help="Export to JSON")
    parser.add_argument("--output", default="flight_schedules_auto.json",
                        help="Output file path")
    args = parser.parse_args()

    db = Database(DB_PATH)
    auto_data = build_schedule_from_db(db)
    db.close()
    
    total = len(auto_data.get("_all", []))
    print(f"\n{'='*50}")
    print(f"Unique flights in database: {total}")
    
    if args.export and total > 0:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(auto_data, f, ensure_ascii=False, indent=2)
        print(f"Exported to: {args.output}")
    
    # Show sample
    if total > 0:
        print(f"\nSample flights:")
        for f in auto_data["_all"][:10]:
            print(f"  {f['flightNo']} | {f['airline']} | {f['aircraft']} | "
                  f"{f['departTime']}-{f['arriveTime']} | {f['departPort']}")


if __name__ == "__main__":
    main()
