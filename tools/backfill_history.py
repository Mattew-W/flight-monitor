"""
Backfill 30 days of MOCK-ONLY price history.
Real data (is_mock=0) is NEVER touched — it must accumulate naturally
via the monitoring engine running over multiple days.
"""
import random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta
from core.database import Database
from config import DB_PATH


def clean_fake_real(db: Database):
    """Remove backfilled records that were incorrectly tagged is_mock=0."""
    conn = db._get_conn()
    deleted = conn.execute(
        "DELETE FROM price_records WHERE is_mock=0 AND batch_id LIKE 'bf%'"
    ).rowcount
    if deleted:
        conn.commit()
        print(f"Cleaned {deleted} fake 'real' records (now is_mock=0 is pure).")
    return deleted


def backfill(db: Database, days: int = 30, max_per_day: int = 10):
    """Backfill mock data ONLY (is_mock=1). Real data is left untouched."""
    conn = db._get_conn()

    # Only find queries with < N days of mock data
    rows = conn.execute("""
        SELECT query_id FROM price_records
        WHERE is_mock = 1
          AND batch_id NOT LIKE 'bf%'
        GROUP BY query_id
        HAVING COUNT(DISTINCT DATE(recorded_at)) < ?
    """, (days,)).fetchall()

    query_ids = [r[0] for r in rows]
    print(f"Found {len(query_ids)} queries needing mock backfill. Processing {days} days...")

    now = datetime.now()
    total = 0

    for qid in query_ids:
        existing = conn.execute(
            "SELECT * FROM price_records WHERE query_id=? AND is_mock=1 "
            "ORDER BY id LIMIT ?",
            (qid, max_per_day)
        ).fetchall()
        if not existing:
            continue

        templates = [dict(r) for r in existing]
        rng = random.Random(qid * 9973)

        for day_ago in range(1, days + 1):
            date = (now - timedelta(days=day_ago)).strftime("%Y-%m-%d")
            batch = "bf" + date.replace("-", "")
            for t in templates:
                jitter = 1.0 + rng.uniform(-0.08, 0.08)
                price = max(100, round(float(t["price"]) * jitter / 10) * 10)
                conn.execute("""
                    INSERT INTO price_records
                    (query_id,airline,flight_no,aircraft,departure_time,
                     arrival_time,departure_airport,arrival_airport,duration,
                     stops,price,cabin_class,source,recorded_at,purchase_url,
                     sub_class,seat_inventory,is_mock,batch_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    qid,
                    t["airline"], t["flight_no"], t.get("aircraft", ""),
                    t.get("departure_time", ""), t.get("arrival_time", ""),
                    t.get("departure_airport", ""), t.get("arrival_airport", ""),
                    t.get("duration", ""), t.get("stops", 0),
                    price, t.get("cabin_class", "economy"),
                    t["source"], date + "T12:00:00",
                    t.get("purchase_url", ""),
                    t.get("sub_class", "Y"), t.get("seat_inventory", 9),
                    1,  # ALWAYS is_mock=1
                    batch,
                ))
                total += 1
        if total % 2000 == 0:
            conn.commit()
            print(f"  {total} records...")

    conn.commit()

    # Summary
    real_count = conn.execute(
        "SELECT COUNT(*) FROM price_records WHERE is_mock=0"
    ).fetchone()[0]
    mock_count = conn.execute(
        "SELECT COUNT(*) FROM price_records WHERE is_mock=1"
    ).fetchone()[0]
    print(f"Done: {total} mock records added.")
    print(f"DB state: {real_count} real + {mock_count} mock = {real_count + mock_count} total")


if __name__ == "__main__":
    db = Database(DB_PATH)
    clean_fake_real(db)
    backfill(db, days=30, max_per_day=10)
    db.close()
