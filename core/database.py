"""
Flight Monitor - Database Manager v2
Thread-safe SQLite with thread-local connection pool, WAL mode, batched writes.
"""
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Set
from .models import SearchQuery, FlightPrice, PriceAlert, AlertHistory

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager with thread-local connection pooling.

    Each thread reuses one connection — no connect/close per operation.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._local = threading.local()
        # Strong-ref set of all live connections (one per thread that touched the DB).
        # sqlite3.Connection does not support weakref, so we hold strong refs and
        # rely on close_all() to release them at shutdown.
        self._all_conns: Set[sqlite3.Connection] = set()
        self._init_db()
        self._migrate()

    def _get_conn(self) -> sqlite3.Connection:
        """Thread-local connection — created once per thread, reused.

        Connections are tracked in a set so close_all() can release every
        thread's connection at shutdown (not just the caller's). sqlite3.Connection
        does not support weakref, so we hold strong refs; for a long-running
        service the set size stays bounded (one entry per live thread).
        """
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            # check_same_thread=False is safe here because each thread gets its OWN
            # connection via thread-local; we never share a conn across threads.
            # Keeping the flag lets sqlite3 skip its (redundant) thread-affinity check
            # which would otherwise fire when a connection is touched by a finalizer.
            conn = sqlite3.connect(self.db_path, timeout=60, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-8000")
            conn.execute("PRAGMA temp_store=MEMORY")
            self._local.conn = conn
            self._all_conns.add(conn)
        return self._local.conn

    def close(self):
        """Close THIS thread's connection (current behavior, kept for compatibility)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        try:
            conn.execute("PRAGMA optimize")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        self._local.conn = None
        self._all_conns.discard(conn)

    def close_all(self):
        """Close every thread's connection. Call at process shutdown.

        Iterates the set of all connections ever issued and closes each.
        Bounded memory: one entry per thread that ever touched the DB.
        """
        with self._lock:
            for conn in list(self._all_conns):
                try:
                    conn.execute("PRAGMA optimize")
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_conns.clear()
            if hasattr(self._local, "conn"):
                self._local.conn = None

    # ── Schema ──────────────────────────────────────────────

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS search_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                departure TEXT NOT NULL, destination TEXT NOT NULL,
                departure_date TEXT NOT NULL, cabin_class TEXT DEFAULT 'economy',
                trip_type TEXT DEFAULT 'oneway', return_date TEXT DEFAULT '',
                is_monitoring INTEGER DEFAULT 0, created_at TEXT DEFAULT '',
                label TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS price_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id INTEGER NOT NULL, airline TEXT, flight_no TEXT,
                aircraft TEXT, departure_time TEXT, arrival_time TEXT,
                departure_airport TEXT, arrival_airport TEXT, duration TEXT,
                stops INTEGER DEFAULT 0, price REAL, cabin_class TEXT DEFAULT 'economy',
                source TEXT, recorded_at TEXT, purchase_url TEXT DEFAULT '',
                sub_class TEXT DEFAULT '', seat_inventory INTEGER DEFAULT 9,
                is_mock INTEGER DEFAULT 0,
                FOREIGN KEY (query_id) REFERENCES search_queries(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id INTEGER NOT NULL, target_price REAL,
                is_active INTEGER DEFAULT 1, notify_email INTEGER DEFAULT 1,
                notify_wechat INTEGER DEFAULT 0, created_at TEXT DEFAULT '',
                last_triggered TEXT DEFAULT '',
                FOREIGN KEY (query_id) REFERENCES search_queries(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER, query_id INTEGER, price REAL,
                target_price REAL, airline TEXT, flight_no TEXT,
                triggered_at TEXT DEFAULT '', message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_price_query ON price_records(query_id);
            CREATE INDEX IF NOT EXISTS idx_price_time ON price_records(recorded_at);
            CREATE INDEX IF NOT EXISTS idx_alert_query ON price_alerts(query_id);
        """)
        conn.commit()

    def _migrate(self):
        conn = self._get_conn()
        try:
            cols = conn.execute("PRAGMA table_info(price_records)").fetchall()
            col_names = {c["name"] for c in cols}
            migrations = [
                ("purchase_url", "ALTER TABLE price_records ADD COLUMN purchase_url TEXT DEFAULT ''"),
                ("batch_id", "ALTER TABLE price_records ADD COLUMN batch_id TEXT DEFAULT ''"),
                ("sub_class", "ALTER TABLE price_records ADD COLUMN sub_class TEXT DEFAULT ''"),
                ("seat_inventory", "ALTER TABLE price_records ADD COLUMN seat_inventory INTEGER DEFAULT 9"),
                ("is_mock", "ALTER TABLE price_records ADD COLUMN is_mock INTEGER DEFAULT 0"),
            ]
            for name, ddl in migrations:
                if name not in col_names:
                    conn.execute(ddl)
                    conn.commit()
                    logger.info(f"Migration: added column '{name}'")
        except Exception as e:
            logger.error(f"Migration error: {e}")

    # ── Search Queries ──────────────────────────────────────

    def add_query(self, q: SearchQuery) -> int:
        with self._lock:
            conn = self._get_conn()
            now = datetime.now().isoformat()
            try:
                cur = conn.execute(
                    "INSERT INTO search_queries (departure, destination, departure_date, "
                    "cabin_class, trip_type, return_date, is_monitoring, created_at, label) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (q.departure, q.destination, q.departure_date, q.cabin_class,
                     q.trip_type, q.return_date, int(q.is_monitoring), now, q.label))
                conn.commit()
                return cur.lastrowid
            except Exception:
                conn.rollback()
                raise

    def get_query(self, query_id: int) -> Optional[SearchQuery]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM search_queries WHERE id=?", (query_id,)).fetchone()
        return self._row_to_query(row) if row else None

    def get_all_queries(self) -> List[SearchQuery]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM search_queries ORDER BY id DESC").fetchall()
        return [self._row_to_query(r) for r in rows]

    def get_monitoring_queries(self) -> List[SearchQuery]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM search_queries WHERE is_monitoring=1 ORDER BY id").fetchall()
        return [self._row_to_query(r) for r in rows]

    def update_query_monitoring(self, query_id: int, monitoring: bool):
        conn = self._get_conn()
        try:
            conn.execute("UPDATE search_queries SET is_monitoring=? WHERE id=?",
                         (int(monitoring), query_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def delete_query(self, query_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute("BEGIN")
            try:
                conn.execute("DELETE FROM price_records WHERE query_id=?", (query_id,))
                conn.execute("DELETE FROM price_alerts WHERE query_id=?", (query_id,))
                conn.execute("DELETE FROM search_queries WHERE id=?", (query_id,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def delete_queries_bulk(self, query_ids: List[int]):
        if not query_ids:
            return
        with self._lock:
            conn = self._get_conn()
            ph = ",".join("?" * len(query_ids))
            conn.execute("BEGIN")
            try:
                conn.execute(f"DELETE FROM price_records WHERE query_id IN ({ph})", query_ids)
                conn.execute(f"DELETE FROM price_alerts WHERE query_id IN ({ph})", query_ids)
                conn.execute(f"DELETE FROM search_queries WHERE id IN ({ph})", query_ids)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # ── Price Records ───────────────────────────────────────

    def add_price_record(self, rec: FlightPrice) -> int:
        conn = self._get_conn()
        now = datetime.now().isoformat()
        try:
            cur = conn.execute(
                "INSERT INTO price_records (query_id, airline, flight_no, aircraft, "
                "departure_time, arrival_time, departure_airport, arrival_airport, "
                "duration, stops, price, cabin_class, source, recorded_at, purchase_url, "
                "sub_class, seat_inventory, is_mock) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec.query_id, rec.airline, rec.flight_no, rec.aircraft,
                 rec.departure_time, rec.arrival_time, rec.departure_airport,
                 rec.arrival_airport, rec.duration, rec.stops, rec.price,
                 rec.cabin_class, rec.source, now, rec.purchase_url,
                 rec.sub_class, rec.seat_inventory, int(rec.is_mock)))
            conn.commit()
            return cur.lastrowid
        except Exception:
            conn.rollback()
            raise

    def add_price_records(self, records: List[FlightPrice]):
        if not records:
            return
        with self._lock:
            conn = self._get_conn()
            batch_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()
            conn.execute("BEGIN")
            try:
                conn.executemany(
                    "INSERT INTO price_records (query_id, airline, flight_no, aircraft, "
                    "departure_time, arrival_time, departure_airport, arrival_airport, "
                    "duration, stops, price, cabin_class, source, recorded_at, "
                    "purchase_url, sub_class, seat_inventory, is_mock, batch_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(r.query_id, r.airline, r.flight_no, r.aircraft,
                      r.departure_time, r.arrival_time, r.departure_airport,
                      r.arrival_airport, r.duration, r.stops, r.price,
                      r.cabin_class, r.source, now, r.purchase_url,
                      r.sub_class, r.seat_inventory, int(r.is_mock), batch_id)
                     for r in records])
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_price_history(self, query_id: int, limit: int = 500,
                          source_filter: str = "") -> List[dict]:
        conn = self._get_conn()
        if source_filter:
            rows = conn.execute(
                "SELECT DATE(recorded_at) as date, MIN(price) as min_price, "
                "AVG(price) as avg_price, MAX(price) as max_price, COUNT(*) as count "
                "FROM price_records WHERE query_id=? AND source=? "
                "GROUP BY DATE(recorded_at) ORDER BY date DESC LIMIT ?",
                (query_id, source_filter, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT DATE(recorded_at) as date, MIN(price) as min_price, "
                "AVG(price) as avg_price, MAX(price) as max_price, COUNT(*) as count "
                "FROM price_records WHERE query_id=? "
                "GROUP BY DATE(recorded_at) ORDER BY date DESC LIMIT ?",
                (query_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_real_price_history(self, query_id: int, limit: int = 500) -> List[dict]:
        """Get historical prices from REAL data only (is_mock=0).

        CRITICAL: Used for ML training data — no synthetic contamination.
        Returns one record per date with min/avg/max.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DATE(recorded_at) as date, MIN(price) as min_price, "
            "AVG(price) as avg_price, MAX(price) as max_price, COUNT(*) as count "
            "FROM price_records WHERE query_id=? AND is_mock=0 "
            "GROUP BY DATE(recorded_at) ORDER BY date DESC LIMIT ?",
            (query_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_real_prices_for_ml(self, query_id: int, limit: int = 200) -> List[dict]:
        """Fetch individual price records from real data for ML training.

        Returns raw price records (not aggregated) with flight-level metadata
        (sub_class, seat_inventory, departure_time, stops).
        Only is_mock=0 records are included.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT price, recorded_at, sub_class, seat_inventory, "
            "departure_time, stops, source "
            "FROM price_records WHERE query_id=? AND is_mock=0 "
            "ORDER BY recorded_at ASC LIMIT ?",
            (query_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_latest_prices(self, query_id: int) -> List[FlightPrice]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT batch_id FROM price_records WHERE query_id=? AND batch_id!='' "
            "ORDER BY id DESC LIMIT 1", (query_id,)).fetchone()
        if row and row["batch_id"]:
            rows = conn.execute(
                "SELECT * FROM price_records WHERE query_id=? AND batch_id=? ORDER BY price ASC",
                (query_id, row["batch_id"])).fetchall()
            return [self._row_to_price(r) for r in rows]
        row = conn.execute(
            "SELECT MAX(recorded_at) as latest FROM price_records WHERE query_id=?",
            (query_id,)).fetchone()
        if not row or not row["latest"]:
            return []
        rows = conn.execute(
            "SELECT * FROM price_records WHERE query_id=? AND recorded_at=? ORDER BY price ASC",
            (query_id, row["latest"])).fetchall()
        return [self._row_to_price(r) for r in rows]

    def get_all_latest_prices(self) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT pr.*, sq.departure, sq.destination, sq.departure_date, sq.label "
            "FROM price_records pr INNER JOIN ("
            "  SELECT query_id, MAX(recorded_at) as latest FROM price_records "
            "  GROUP BY query_id) latest_pr "
            "ON pr.query_id = latest_pr.query_id AND pr.recorded_at = latest_pr.latest "
            "INNER JOIN search_queries sq ON pr.query_id = sq.id "
            "ORDER BY pr.query_id, pr.price ASC").fetchall()
        return [dict(r) for r in rows]

    def get_price_stats(self, query_id: int) -> dict:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT MIN(price) as min_price, MAX(price) as max_price, "
            "AVG(price) as avg_price, COUNT(*) as total_records "
            "FROM price_records WHERE query_id=?", (query_id,)).fetchone()
        if not row or not row["total_records"]:
            return {"min_price": 0, "max_price": 0, "avg_price": 0, "total_records": 0}
        return dict(row)

    def get_daily_min_prices(self, query_id: int, real_only: bool = True,
                             limit: int = 500) -> List[dict]:
        """Return daily minimum prices for a query, oldest first.

        Public accessor so callers (e.g. routes) don't need to touch _get_conn()
        or hand-roll SQL. Each row: {"date": "YYYY-MM-DD", "min_price": float}.
        """
        conn = self._get_conn()
        mock_clause = "AND is_mock=0" if real_only else ""
        rows = conn.execute(
            f"SELECT DATE(recorded_at) as date, MIN(price) as min_price "
            f"FROM price_records WHERE query_id=? {mock_clause} "
            f"GROUP BY DATE(recorded_at) ORDER BY date ASC LIMIT ?",
            (query_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_daily_cheapest_records(self, query_id: int, real_only: bool = True,
                                   include_mock: bool = False,
                                   limit: int = 500) -> List[dict]:
        """Get the exact cheapest price record per day with full metadata.

        Public accessor for price_prediction.py and chart generators.
        Each row includes: date, price, departure_time, sub_class,
        seat_inventory, stops.
        """
        conn = self._get_conn()
        source_cond = "AND source = 'ctrip_browser'" if real_only else ""
        mock_cond = "" if include_mock else "AND is_mock = 0"
        sql = f"""
            SELECT pr.*, DATE(pr.recorded_at) as date
            FROM price_records pr
            INNER JOIN (
                SELECT DATE(recorded_at) as date, MIN(price) as min_price
                FROM price_records
                WHERE query_id = ? {mock_cond} {source_cond}
                GROUP BY DATE(recorded_at)
            ) grouped
            ON DATE(pr.recorded_at) = grouped.date
               AND pr.price = grouped.min_price
            WHERE pr.query_id = ? {mock_cond} {source_cond}
            ORDER BY date ASC LIMIT ?
        """
        rows = conn.execute(sql, (query_id, query_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_all_prices_for_export(self, query_id: Optional[int] = None) -> List[dict]:
        conn = self._get_conn()
        if query_id is not None:
            rows = conn.execute(
                "SELECT pr.*, sq.departure, sq.destination, sq.departure_date "
                "FROM price_records pr JOIN search_queries sq ON pr.query_id = sq.id "
                "WHERE pr.query_id=? ORDER BY pr.recorded_at DESC", (query_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT pr.*, sq.departure, sq.destination, sq.departure_date "
                "FROM price_records pr JOIN search_queries sq ON pr.query_id = sq.id "
                "ORDER BY pr.recorded_at DESC LIMIT 50000").fetchall()
        return [dict(r) for r in rows]

    # ── Alerts ──────────────────────────────────────────────

    def add_alert(self, alert: PriceAlert) -> int:
        conn = self._get_conn()
        now = datetime.now().isoformat()
        try:
            cur = conn.execute(
                "INSERT INTO price_alerts (query_id, target_price, is_active, "
                "notify_email, notify_wechat, created_at, last_triggered) "
                "VALUES (?,?,?,?,?,?,?)",
                (alert.query_id, alert.target_price, int(alert.is_active),
                 int(alert.notify_email), int(alert.notify_wechat), now, ""))
            conn.commit()
            return cur.lastrowid
        except Exception:
            conn.rollback()
            raise

    def get_alerts(self, query_id: Optional[int] = None) -> List[PriceAlert]:
        conn = self._get_conn()
        if query_id is not None:
            rows = conn.execute("SELECT * FROM price_alerts WHERE query_id=? ORDER BY id DESC",
                                (query_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM price_alerts ORDER BY id DESC").fetchall()
        return [self._row_to_alert(r) for r in rows]

    def get_active_alerts(self) -> List[PriceAlert]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM price_alerts WHERE is_active=1").fetchall()
        return [self._row_to_alert(r) for r in rows]

    def update_alert(self, alert_id: int, target_price: Optional[float] = None,
                     is_active: Optional[bool] = None):
        conn = self._get_conn()
        try:
            if target_price is not None:
                conn.execute("UPDATE price_alerts SET target_price=? WHERE id=?", (target_price, alert_id))
            if is_active is not None:
                conn.execute("UPDATE price_alerts SET is_active=? WHERE id=?", (int(is_active), alert_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def delete_alert(self, alert_id: int):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM price_alerts WHERE id=?", (alert_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def mark_alert_triggered(self, alert_id: int):
        conn = self._get_conn()
        try:
            conn.execute("UPDATE price_alerts SET last_triggered=? WHERE id=?",
                         (datetime.now().isoformat(), alert_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def add_alert_history(self, hist: AlertHistory) -> int:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "INSERT INTO alert_history (alert_id, query_id, price, target_price, "
                "airline, flight_no, triggered_at, message) VALUES (?,?,?,?,?,?,?,?)",
                (hist.alert_id, hist.query_id, hist.price, hist.target_price,
                 hist.airline, hist.flight_no, datetime.now().isoformat(), hist.message))
            conn.commit()
            return cur.lastrowid
        except Exception:
            conn.rollback()
            raise

    def get_alert_history(self, limit: int = 50) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT ah.*, sq.departure, sq.destination, sq.departure_date "
            "FROM alert_history ah LEFT JOIN search_queries sq ON ah.query_id = sq.id "
            "ORDER BY ah.triggered_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── Maintenance ─────────────────────────────────────────

    def prune_expired_records(self, days_old: int = 45):
        with self._lock:
            conn = self._get_conn()
            cutoff = (datetime.now() - timedelta(days=days_old)).isoformat()
            try:
                cur = conn.execute(
                    "DELETE FROM price_records WHERE rowid IN ("
                    "  SELECT pr.rowid FROM price_records pr "
                    "  JOIN search_queries sq ON pr.query_id = sq.id "
                    "  WHERE pr.recorded_at < ? AND sq.is_monitoring = 0)", (cutoff,))
                conn.commit()
                if cur.rowcount:
                    logger.info(f"Pruning: removed {cur.rowcount} old records")
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    # ── Helpers ─────────────────────────────────────────────

    def _row_to_query(self, row) -> SearchQuery:
        return SearchQuery(
            id=row["id"], departure=row["departure"], destination=row["destination"],
            departure_date=row["departure_date"], cabin_class=row["cabin_class"],
            trip_type=row["trip_type"], return_date=row["return_date"],
            is_monitoring=bool(row["is_monitoring"]), created_at=row["created_at"],
            label=row["label"])

    def _row_to_price(self, row) -> FlightPrice:
        # NOTE: `"col" in row` tests VALUES for sqlite3.Row, not column names.
        # Always use `row.keys()` to check column existence.
        keys = row.keys()
        return FlightPrice(
            id=row["id"], query_id=row["query_id"], airline=row["airline"],
            flight_no=row["flight_no"], aircraft=row["aircraft"],
            departure_time=row["departure_time"], arrival_time=row["arrival_time"],
            departure_airport=row["departure_airport"], arrival_airport=row["arrival_airport"],
            duration=row["duration"], stops=row["stops"], price=row["price"],
            cabin_class=row["cabin_class"], source=row["source"],
            recorded_at=row["recorded_at"],
            purchase_url=row["purchase_url"] if "purchase_url" in keys else "",
            sub_class=row["sub_class"] if "sub_class" in keys else "",
            seat_inventory=row["seat_inventory"] if "seat_inventory" in keys else 9,
            is_mock=bool(row["is_mock"]) if "is_mock" in keys else False)

    def _row_to_alert(self, row) -> PriceAlert:
        return PriceAlert(
            id=row["id"], query_id=row["query_id"], target_price=row["target_price"],
            is_active=bool(row["is_active"]), notify_email=bool(row["notify_email"]),
            notify_wechat=bool(row["notify_wechat"]), created_at=row["created_at"],
            last_triggered=row["last_triggered"])
