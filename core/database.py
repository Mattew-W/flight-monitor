"""
Flight Monitor - Database Manager
Handles SQLite operations for all persistent data.
"""
import logging
import sqlite3
import os
import threading
import uuid
from datetime import datetime
from typing import List, Optional
from .models import SearchQuery, FlightPrice, PriceAlert, AlertHistory

logger = logging.getLogger(__name__)

class Database:
    """SQLite database manager for flight monitor."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()
        self._migrate()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def close(self):
        """Close database connection on shutdown."""
        pass  # Connections are per-operation, nothing to close

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
                CREATE TABLE IF NOT EXISTS search_queries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    departure TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    departure_date TEXT NOT NULL,
                    cabin_class TEXT DEFAULT 'economy',
                    trip_type TEXT DEFAULT 'oneway',
                    return_date TEXT DEFAULT '',
                    is_monitoring INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT '',
                    label TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS price_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id INTEGER NOT NULL,
                    airline TEXT,
                    flight_no TEXT,
                    aircraft TEXT,
                    departure_time TEXT,
                    arrival_time TEXT,
                    departure_airport TEXT,
                    arrival_airport TEXT,
                    duration TEXT,
                    stops INTEGER DEFAULT 0,
                    price REAL,
                    cabin_class TEXT DEFAULT 'economy',
                    source TEXT,
                    recorded_at TEXT,
                    purchase_url TEXT DEFAULT '',
                    FOREIGN KEY (query_id) REFERENCES search_queries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id INTEGER NOT NULL,
                    target_price REAL,
                    is_active INTEGER DEFAULT 1,
                    notify_email INTEGER DEFAULT 1,
                    notify_wechat INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT '',
                    last_triggered TEXT DEFAULT '',
                    FOREIGN KEY (query_id) REFERENCES search_queries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER,
                    query_id INTEGER,
                    price REAL,
                    target_price REAL,
                    airline TEXT,
                    flight_no TEXT,
                    triggered_at TEXT DEFAULT '',
                    message TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_price_query ON price_records(query_id);
                CREATE INDEX IF NOT EXISTS idx_price_time ON price_records(recorded_at);
                CREATE INDEX IF NOT EXISTS idx_alert_query ON price_alerts(query_id);
            """)
        conn.commit()

    def _migrate(self):
        """Add missing columns to existing tables (backward compat)."""
        conn = self._get_conn()
        try:
            cols = conn.execute("PRAGMA table_info(price_records)").fetchall()
            col_names = {c["name"] for c in cols}
            migrations = [
                ("purchase_url", "ALTER TABLE price_records ADD COLUMN purchase_url TEXT DEFAULT ''"),
                ("batch_id", "ALTER TABLE price_records ADD COLUMN batch_id TEXT DEFAULT ''"),
            ]
            for col_name, ddl in migrations:
                if col_name not in col_names:
                    conn.execute(ddl)
                    conn.commit()
                    logger.info(f"Migration: added column '{col_name}'")
        except Exception as e:
            logger.error(f"Migration error: {e}")

    # ── Search Queries ──────────────────────────────────────────

    def add_query(self, q: SearchQuery) -> int:
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                """INSERT INTO search_queries
                   (departure, destination, departure_date, cabin_class,
                    trip_type, return_date, is_monitoring, created_at, label)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (q.departure, q.destination, q.departure_date, q.cabin_class,
                 q.trip_type, q.return_date, int(q.is_monitoring), now, q.label)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_query(self, query_id: int) -> Optional[SearchQuery]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM search_queries WHERE id=?", (query_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_query(row)
        finally:
            conn.close()

    def get_all_queries(self) -> List[SearchQuery]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM search_queries ORDER BY id DESC"
            ).fetchall()
            return [self._row_to_query(r) for r in rows]
        finally:
            conn.close()

    def get_monitoring_queries(self) -> List[SearchQuery]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM search_queries WHERE is_monitoring=1 ORDER BY id"
            ).fetchall()
            return [self._row_to_query(r) for r in rows]
        finally:
            conn.close()

    def update_query_monitoring(self, query_id: int, monitoring: bool):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE search_queries SET is_monitoring=? WHERE id=?",
                (int(monitoring), query_id)
            )
            conn.commit()
        finally:
            conn.close()

    def delete_query(self, query_id: int):
        """Delete a query and cascade-delete its price records.

        Uses transaction with foreign_keys=OFF temporarily to avoid
        per-row cascade checks, then re-enables and verifies.
        """
        conn = self._get_conn()
        try:
            # Count first so we can decide fast path
            cnt = conn.execute(
                "SELECT COUNT(*) FROM price_records WHERE query_id=?",
                (query_id,),
            ).fetchone()[0]

            if cnt == 0:
                # Fast path: no related records
                conn.execute("DELETE FROM search_queries WHERE id=?", (query_id,))
                conn.commit()
                return

            # Batched delete + drop the index temporarily for speed on big queries
            # Begin transaction
            conn.execute("BEGIN")
            try:
                # Batch delete price records (1000 at a time)
                while True:
                    deleted = conn.execute(
                        "DELETE FROM price_records WHERE query_id=? AND id IN "
                        "(SELECT id FROM price_records WHERE query_id=? LIMIT 1000)",
                        (query_id, query_id),
                    ).rowcount
                    if deleted == 0:
                        break
                conn.execute("DELETE FROM search_queries WHERE id=?", (query_id,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()

    def delete_queries_bulk(self, query_ids: List[int]):
        """Bulk delete multiple queries in a single transaction."""
        if not query_ids:
            return
        placeholders = ",".join("?" * len(query_ids))
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    f"DELETE FROM price_records WHERE query_id IN ({placeholders})",
                    query_ids,
                )
                conn.execute(
                    f"DELETE FROM search_queries WHERE id IN ({placeholders})",
                    query_ids,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()

    # ── Price Records ───────────────────────────────────────────

    def add_price_record(self, rec: FlightPrice) -> int:
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                """INSERT INTO price_records
                   (query_id, airline, flight_no, aircraft, departure_time,
                    arrival_time, departure_airport, arrival_airport, duration,
                    stops, price, cabin_class, source, recorded_at, purchase_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rec.query_id, rec.airline, rec.flight_no, rec.aircraft,
                 rec.departure_time, rec.arrival_time, rec.departure_airport,
                 rec.arrival_airport, rec.duration, rec.stops, rec.price,
                 rec.cabin_class, rec.source, now, rec.purchase_url)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def add_price_records(self, records: List[FlightPrice]):
        conn = self._get_conn()
        try:
            batch_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()
            conn.executemany(
                """INSERT INTO price_records
                   (query_id, airline, flight_no, aircraft, departure_time,
                    arrival_time, departure_airport, arrival_airport, duration,
                    stops, price, cabin_class, source, recorded_at, purchase_url, batch_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(r.query_id, r.airline, r.flight_no, r.aircraft,
                  r.departure_time, r.arrival_time, r.departure_airport,
                  r.arrival_airport, r.duration, r.stops, r.price,
                  r.cabin_class, r.source, now, r.purchase_url, batch_id) for r in records]
            )
            conn.commit()
        finally:
            conn.close()

    def get_price_history(self, query_id: int, limit: int = 500,
                          source_filter: str = "") -> List[dict]:
        conn = self._get_conn()
        try:
            if source_filter:
                rows = conn.execute(
                    """SELECT
                           DATE(recorded_at) as date,
                           MIN(price) as min_price,
                           AVG(price) as avg_price,
                           MAX(price) as max_price,
                           COUNT(*) as count
                       FROM price_records
                       WHERE query_id=? AND source=?
                       GROUP BY DATE(recorded_at)
                       ORDER BY date DESC
                       LIMIT ?""",
                    (query_id, source_filter, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT
                           DATE(recorded_at) as date,
                           MIN(price) as min_price,
                           AVG(price) as avg_price,
                           MAX(price) as max_price,
                           COUNT(*) as count
                       FROM price_records
                       WHERE query_id=?
                       GROUP BY DATE(recorded_at)
                       ORDER BY date DESC
                       LIMIT ?""",
                    (query_id, limit)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_latest_prices(self, query_id: int) -> List[FlightPrice]:
        conn = self._get_conn()
        try:
            # Get the latest batch_id to avoid mixing different search batches
            row = conn.execute(
                "SELECT batch_id FROM price_records WHERE query_id=? AND batch_id!='' ORDER BY id DESC LIMIT 1",
                (query_id,)
            ).fetchone()
            if row and row["batch_id"]:
                rows = conn.execute(
                    "SELECT * FROM price_records WHERE query_id=? AND batch_id=? ORDER BY price ASC",
                    (query_id, row["batch_id"])
                ).fetchall()
                return [self._row_to_price(r) for r in rows]
            # Fallback for old records without batch_id
            row = conn.execute(
                "SELECT MAX(recorded_at) as latest FROM price_records WHERE query_id=?",
                (query_id,)
            ).fetchone()
            if not row or not row["latest"]:
                return []
            rows = conn.execute(
                "SELECT * FROM price_records WHERE query_id=? AND recorded_at=? ORDER BY price ASC",
                (query_id, row["latest"])
            ).fetchall()
            return [self._row_to_price(r) for r in rows]
        finally:
            conn.close()

    def get_all_latest_prices(self) -> List[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT pr.*, sq.departure, sq.destination, sq.departure_date, sq.label
                   FROM price_records pr
                   INNER JOIN (
                       SELECT query_id, MAX(recorded_at) as latest
                       FROM price_records
                       GROUP BY query_id
                   ) latest_pr ON pr.query_id = latest_pr.query_id AND pr.recorded_at = latest_pr.latest
                   INNER JOIN search_queries sq ON pr.query_id = sq.id
                   ORDER BY pr.query_id, pr.price ASC"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_price_stats(self, query_id: int) -> dict:
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       AVG(price) as avg_price,
                       COUNT(*) as total_records
                   FROM price_records WHERE query_id=?""",
                (query_id,)
            ).fetchone()
            if not row or not row["total_records"]:
                return {"min_price": 0, "max_price": 0, "avg_price": 0, "total_records": 0}
            return dict(row)
        finally:
            conn.close()

    def get_all_prices_for_export(self, query_id: Optional[int] = None) -> List[dict]:
        """Get all price records for CSV export."""
        conn = self._get_conn()
        try:
            if query_id:
                rows = conn.execute(
                    """SELECT pr.*, sq.departure, sq.destination, sq.departure_date
                       FROM price_records pr
                       JOIN search_queries sq ON pr.query_id = sq.id
                       WHERE pr.query_id=?
                       ORDER BY pr.recorded_at DESC""",
                    (query_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT pr.*, sq.departure, sq.destination, sq.departure_date
                       FROM price_records pr
                       JOIN search_queries sq ON pr.query_id = sq.id
                       ORDER BY pr.recorded_at DESC"""
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Alerts ──────────────────────────────────────────────────

    def add_alert(self, alert: PriceAlert) -> int:
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                """INSERT INTO price_alerts
                   (query_id, target_price, is_active, notify_email,
                    notify_wechat, created_at, last_triggered)
                   VALUES (?,?,?,?,?,?,?)""",
                (alert.query_id, alert.target_price, int(alert.is_active),
                 int(alert.notify_email), int(alert.notify_wechat), now, "")
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_alerts(self, query_id: Optional[int] = None) -> List[PriceAlert]:
        conn = self._get_conn()
        try:
            if query_id:
                rows = conn.execute(
                    "SELECT * FROM price_alerts WHERE query_id=? ORDER BY id DESC",
                    (query_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM price_alerts ORDER BY id DESC"
                ).fetchall()
            return [self._row_to_alert(r) for r in rows]
        finally:
            conn.close()

    def get_active_alerts(self) -> List[PriceAlert]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM price_alerts WHERE is_active=1"
            ).fetchall()
            return [self._row_to_alert(r) for r in rows]
        finally:
            conn.close()

    def update_alert(self, alert_id: int, target_price: Optional[float] = None,
                     is_active: Optional[bool] = None):
        conn = self._get_conn()
        try:
            if target_price is not None:
                conn.execute(
                    "UPDATE price_alerts SET target_price=? WHERE id=?",
                    (target_price, alert_id)
                )
            if is_active is not None:
                conn.execute(
                    "UPDATE price_alerts SET is_active=? WHERE id=?",
                    (int(is_active), alert_id)
                )
            conn.commit()
        finally:
            conn.close()

    def delete_alert(self, alert_id: int):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM price_alerts WHERE id=?", (alert_id,))
            conn.commit()
        finally:
            conn.close()

    def mark_alert_triggered(self, alert_id: int):
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE price_alerts SET last_triggered=? WHERE id=?",
                (now, alert_id)
            )
            conn.commit()
        finally:
            conn.close()

    # ── Alert History ───────────────────────────────────────────

    def add_alert_history(self, hist: AlertHistory) -> int:
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                """INSERT INTO alert_history
                   (alert_id, query_id, price, target_price, airline,
                    flight_no, triggered_at, message)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (hist.alert_id, hist.query_id, hist.price, hist.target_price,
                 hist.airline, hist.flight_no, now, hist.message)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_alert_history(self, limit: int = 50) -> List[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT ah.*, sq.departure, sq.destination, sq.departure_date
                   FROM alert_history ah
                   LEFT JOIN search_queries sq ON ah.query_id = sq.id
                   ORDER BY ah.triggered_at DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Helpers ─────────────────────────────────────────────────

    def _row_to_query(self, row) -> SearchQuery:
        return SearchQuery(
            id=row["id"],
            departure=row["departure"],
            destination=row["destination"],
            departure_date=row["departure_date"],
            cabin_class=row["cabin_class"],
            trip_type=row["trip_type"],
            return_date=row["return_date"],
            is_monitoring=bool(row["is_monitoring"]),
            created_at=row["created_at"],
            label=row["label"],
        )

    def prune_expired_records(self, days_old: int = 45):
        """Delete historical prices older than X days to prevent SQLite database bloat."""
        conn = self._get_conn()
        try:
            from datetime import timedelta
            cutoff_date = (datetime.now() - timedelta(days=days_old)).isoformat()
            cur = conn.execute(
                "DELETE FROM price_records WHERE recorded_at < ?",
                (cutoff_date,)
            )
            conn.commit()
            logger.info(f"Database Pruning: Removed {cur.rowcount} old price records.")
            return cur.rowcount
        except Exception as e:
            logger.error(f"Pruning error: {e}")
            return 0
        finally:
            conn.close()

    def _row_to_price(self, row) -> FlightPrice:
        return FlightPrice(
            id=row["id"], query_id=row["query_id"], airline=row["airline"],
            flight_no=row["flight_no"], aircraft=row["aircraft"],
            departure_time=row["departure_time"], arrival_time=row["arrival_time"],
            departure_airport=row["departure_airport"], arrival_airport=row["arrival_airport"],
            duration=row["duration"], stops=row["stops"], price=row["price"],
            cabin_class=row["cabin_class"], source=row["source"],
            recorded_at=row["recorded_at"],
            purchase_url=row["purchase_url"] if "purchase_url" in row else "",
        )

    def _row_to_alert(self, row) -> PriceAlert:
        return PriceAlert(
            id=row["id"], query_id=row["query_id"],
            target_price=row["target_price"], is_active=bool(row["is_active"]),
            notify_email=bool(row["notify_email"]),
            notify_wechat=bool(row["notify_wechat"]),
            created_at=row["created_at"], last_triggered=row["last_triggered"],
        )
