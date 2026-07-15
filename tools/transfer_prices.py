"""
Transfer real BJS->SHA 88-day price pattern to all other routes.
Each route gets the same proportional price curve, scaled to its own base price.
This preserves real-world price dynamics (weekend spikes, holiday trends, etc.)

Run as:  python transfer_prices.py
(NOT imported — module-level code writes to the DB.)
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime
from core.database import Database
from config import DB_PATH, POPULAR_ROUTES
from datasources.mock_source import get_route_base_price


def main():
    db = Database(DB_PATH)
    conn = db._get_conn()

    # Step 1: Extract the real BJS->SHA daily price ratio curve
    rows = conn.execute("""
        SELECT DATE(recorded_at) as date, MIN(price) as min_price
        FROM price_records WHERE is_mock=0 AND query_id=1595
        GROUP BY DATE(recorded_at) ORDER BY date ASC
    """).fetchall()

    if not rows:
        print("No real price data found at qid=1595!")
        db.close()
        return

    prices = [r["min_price"] for r in rows]
    dates = [r["date"] for r in rows]
    base = max(prices[0], 1)  # guard against divide-by-zero if first day price is 0
    ratios = [p / base for p in prices]

    print("BJS->SHA pattern (88 days): base=%.0f, min=%.0f, max=%.0f" % (
        base, min(prices), max(prices)))

    # Step 2: Apply to all routes
    imported = 0
    rng = random.Random(42)

    for route in POPULAR_ROUTES:
        dep, dst = route["departure"], route["destination"]
        if dep == dst: continue

        # Each route's own base price, scaled from "competition" level routes
        route_base = get_route_base_price(dep, dst)

        # Create query
        now = datetime.now().isoformat()
        qid = conn.execute(
            "INSERT INTO search_queries (departure,destination,departure_date,cabin_class,created_at,label) VALUES (?,?,?,?,?,?)",
            (dep, dst, "2026-08-15", "economy", now, "%s->%s (迁移)" % (dep, dst))
        ).lastrowid

        for i, (date, ratio) in enumerate(zip(dates, ratios)):
            price = round(route_base * ratio / 10) * 10
            # Add small random noise to avoid exact duplicates
            price = max(100, price + rng.randint(-30, 30))

            conn.execute("""
                INSERT INTO price_records
                (query_id, airline, flight_no, departure_time, arrival_time,
                 departure_airport, arrival_airport, duration, stops, price,
                 cabin_class, source, recorded_at,
                 sub_class, seat_inventory, is_mock, batch_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                qid, "迁移数据", "XX0000",
                "%02d:00" % rng.randint(6, 21),
                "%02d:30" % rng.randint(8, 23),
                dep, dst, "%dh%dm" % (rng.randint(1, 4), rng.randint(0, 59)),
                0, price, "economy",
                "transfer",
                date + "T12:00:00",
                rng.choice(["Y","B","M","H","K"]),
                rng.randint(1, 9),
                1,  # is_mock=1 — honest about being synthetic
                "transfer_pattern",
            ))
            imported += 1

    conn.commit()
    real = conn.execute("SELECT COUNT(*) FROM price_records WHERE is_mock=0").fetchone()[0]
    mock = conn.execute("SELECT COUNT(*) FROM price_records WHERE is_mock=1").fetchone()[0]
    print("Imported: %d records across %d routes" % (imported, len(POPULAR_ROUTES)))
    print("DB: %d real + %d mock = %d total" % (real, mock, real + mock))
    db.close()


if __name__ == "__main__":
    main()
