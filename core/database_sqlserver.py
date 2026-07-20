"""
Flight Monitor - SQL Server Express 2025 Backend
===================================================
Drop-in replacement for ``core/database.py`` when ``DB_ENGINE=sqlserver``.

Prerequisites:
    1. SQL Server 2025 Express (or any edition) running
    2. pyodbc  (``pip install pyodbc``)
    3. ODBC Driver 17/18 for SQL Server

Usage
-----
In ``config.py``::

    DB_ENGINE = 'sqlserver'          # 'sqlite' (default) | 'sqlserver'
    DB_NAME   = 'flight_monitor'
    DB_SERVER = r".\SQLEXPRESS"

Then in ``main.py``::

    from core.database_sqlserver import Database  # instead of database.py
"""
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional, Set

from .models import SearchQuery, FlightPrice, PriceAlert, AlertHistory

try:
    import pyodbc
except ImportError:
    pyodbc = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class Database:
    """SQL Server Database with the same public API as
    ``core.database.Database`` (SQLite version).

    Swapping backends requires zero changes to callers — only the import
    and ``DB_ENGINE`` config toggle.
    """

    def __init__(
        self,
        server: str = r".\SQLEXPRESS",
        database: str = "flight_monitor",
        trusted_connection: bool = True,
        trust_server_cert: bool = True,
    ):
        if pyodbc is None:
            raise RuntimeError(
                "pyodbc is not installed.  pip install pyodbc\n"
                "Also install ODBC Driver 17/18 for SQL Server."
            )
        self.server = server
        self.database = database
        self.trusted_connection = trusted_connection
        self.trust_server_cert = trust_server_cert

        self._lock = threading.RLock()
        self._local = threading.local()
        self._all_conns: Set[pyodbc.Connection] = set()

        self._init_db()
        self._migrate()

    # ── Connection pooling (mirrors SQLite version) ────────────

    def _connection_string(self) -> str:
        parts = [
            "DRIVER={ODBC Driver 18 for SQL Server}",
            f"SERVER={self.server}",
            f"DATABASE={self.database}",
        ]
        if self.trusted_connection:
            parts.append("Trusted_Connection=yes")
        if self.trust_server_cert:
            parts.append("TrustServerCertificate=yes")
        return ";".join(parts)

    def _get_conn(self) -> pyodbc.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            for attempt in range(3):
                try:
                    conn = pyodbc.connect(
                        self._connection_string(),
                        autocommit=False,
                        timeout=30,
                    )
                    break
                except Exception:
                    if attempt < 2:
                        time.sleep(1)
                    else:
                        raise
            try:
                conn.execute("SET NOCOUNT ON")
            except Exception:
                pass
            self._local.conn = conn
            self._all_conns.add(conn)
        return self._local.conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        try:
            conn.commit()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        self._local.conn = None
        self._all_conns.discard(conn)

    def close_all(self) -> None:
        with self._lock:
            for conn in list(self._all_conns):
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_conns.clear()
            if hasattr(self._local, "conn"):
                self._local.conn = None

    # ── Schema ─────────────────────────────────────────────────

    def _init_db(self) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()

        stmts = [
            """IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='search_queries' AND xtype='U')
            CREATE TABLE search_queries (
                id             INT IDENTITY(1,1) PRIMARY KEY,
                departure      NVARCHAR(100) NOT NULL,
                destination    NVARCHAR(100) NOT NULL,
                departure_date NVARCHAR(20)  NOT NULL,
                cabin_class    NVARCHAR(20)  DEFAULT 'economy',
                trip_type      NVARCHAR(20)  DEFAULT 'oneway',
                return_date    NVARCHAR(20)  DEFAULT '',
                is_monitoring  BIT DEFAULT 0,
                created_at     NVARCHAR(30) DEFAULT '',
                label          NVARCHAR(200) DEFAULT ''
            )""",
            """IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='price_records' AND xtype='U')
            CREATE TABLE price_records (
                id               INT IDENTITY(1,1) PRIMARY KEY,
                query_id         INT NOT NULL,
                airline          NVARCHAR(100) DEFAULT '',
                flight_no        NVARCHAR(20)  DEFAULT '',
                aircraft         NVARCHAR(50)  DEFAULT '',
                departure_time   NVARCHAR(30) DEFAULT '',
                arrival_time     NVARCHAR(30) DEFAULT '',
                departure_airport NVARCHAR(100) DEFAULT '',
                arrival_airport  NVARCHAR(100) DEFAULT '',
                duration         NVARCHAR(20) DEFAULT '',
                stops            INT DEFAULT 0,
                price            FLOAT,
                cabin_class      NVARCHAR(20) DEFAULT 'economy',
                source           NVARCHAR(50) DEFAULT '',
                recorded_at      NVARCHAR(30) DEFAULT '',
                purchase_url     NVARCHAR(500) DEFAULT '',
                sub_class        NVARCHAR(20) DEFAULT '',
                seat_inventory   INT DEFAULT 9,
                is_mock          BIT DEFAULT 0,
                CONSTRAINT FK_price_query FOREIGN KEY (query_id)
                    REFERENCES search_queries(id) ON DELETE CASCADE
            )""",
            """IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='price_alerts' AND xtype='U')
            CREATE TABLE price_alerts (
                id             INT IDENTITY(1,1) PRIMARY KEY,
                query_id       INT NOT NULL,
                target_price   FLOAT,
                is_active      BIT DEFAULT 1,
                notify_email   BIT DEFAULT 1,
                notify_wechat  BIT DEFAULT 0,
                created_at     NVARCHAR(30) DEFAULT '',
                last_triggered NVARCHAR(30) DEFAULT '',
                CONSTRAINT FK_alert_query FOREIGN KEY (query_id)
                    REFERENCES search_queries(id) ON DELETE CASCADE
            )""",
            """IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='alert_history' AND xtype='U')
            CREATE TABLE alert_history (
                id           INT IDENTITY(1,1) PRIMARY KEY,
                alert_id     INT,
                query_id     INT,
                price        FLOAT,
                target_price FLOAT,
                airline      NVARCHAR(100) DEFAULT '',
                flight_no    NVARCHAR(20)  DEFAULT '',
                triggered_at NVARCHAR(30) DEFAULT '',
                message      NVARCHAR(500) DEFAULT ''
            )""",
            """IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_price_query' AND object_id=OBJECT_ID('price_records'))
            CREATE INDEX idx_price_query ON price_records(query_id)""",
            """IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_price_time' AND object_id=OBJECT_ID('price_records'))
            CREATE INDEX idx_price_time ON price_records(recorded_at)""",
            """IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_alert_query' AND object_id=OBJECT_ID('price_alerts'))
            CREATE INDEX idx_alert_query ON price_alerts(query_id)""",
        ]
        for s in stmts:
            cursor.execute(s)
        conn.commit()

    def _migrate(self) -> None:
        pass

    # ── helpers ─────────────────────────────────────────────────

    @staticmethod
    def _to_searchquery(row) -> SearchQuery:
        return SearchQuery(
            id=row.id, departure=row.departure, destination=row.destination,
            departure_date=row.departure_date, cabin_class=row.cabin_class or "economy",
            trip_type=row.trip_type or "oneway", return_date=row.return_date or "",
            is_monitoring=bool(row.is_monitoring), created_at=row.created_at or "",
            label=row.label or "",
        )

    @staticmethod
    def _to_flightprice(row) -> FlightPrice:
        return FlightPrice(
            id=row.id, query_id=row.query_id, airline=row.airline or "",
            flight_no=row.flight_no or "", aircraft=row.aircraft or "",
            departure_time=row.departure_time or "", arrival_time=row.arrival_time or "",
            departure_airport=row.departure_airport or "",
            arrival_airport=row.arrival_airport or "",
            duration=row.duration or "", stops=row.stops or 0,
            price=float(row.price) if row.price is not None else 0.0,
            cabin_class=row.cabin_class or "economy",
            source=row.source or "", recorded_at=row.recorded_at or "",
            purchase_url=row.purchase_url or "",
        )

    # ── search_queries ─────────────────────────────────────────

    def add_query(self, departure: str, destination: str, departure_date: str,
                  cabin_class: str = "economy", trip_type: str = "oneway",
                  return_date: str = "", label: str = "") -> int:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO search_queries (departure,destination,departure_date,"
                " cabin_class,trip_type,return_date,is_monitoring,created_at,label)"
                " VALUES (?,?,?,?,?,?,0,?,?)",
                departure, destination, departure_date, cabin_class, trip_type,
                return_date, datetime.now().isoformat(), label,
            )
            conn.commit()
            row = conn.execute("SELECT @@IDENTITY").fetchone()
            return int(row[0])

    def get_monitoring_queries(self) -> List[SearchQuery]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM search_queries WHERE is_monitoring=1"
        ).fetchall()
        return [self._to_searchquery(r) for r in rows]

    def get_query(self, query_id: int) -> Optional[SearchQuery]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM search_queries WHERE id=?", query_id
        ).fetchone()
        return self._to_searchquery(row) if row else None

    def get_all_queries(self) -> List[SearchQuery]:
        conn = self._get_conn()
        return [self._to_searchquery(r)
                for r in conn.execute("SELECT * FROM search_queries").fetchall()]

    def update_query_monitoring(self, query_id: int, is_monitoring: bool) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE search_queries SET is_monitoring=? WHERE id=?",
                int(is_monitoring), query_id,
            )
            conn.commit()

    def delete_query(self, query_id: int) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.execute("DELETE FROM price_records WHERE query_id=?", query_id)
            conn.execute("DELETE FROM price_alerts WHERE query_id=?", query_id)
            conn.execute("DELETE FROM search_queries WHERE id=?", query_id)
            conn.commit()

    def delete_queries_bulk(self, query_ids: List[int]) -> int:
        if not query_ids:
            return 0
        conn = self._get_conn()
        with self._lock:
            placeholders = ",".join("?" * len(query_ids))
            conn.execute(
                f"DELETE FROM price_records WHERE query_id IN ({placeholders})",
                query_ids,
            )
            conn.execute(
                f"DELETE FROM price_alerts WHERE query_id IN ({placeholders})",
                query_ids,
            )
            conn.execute(
                f"DELETE FROM search_queries WHERE id IN ({placeholders})",
                query_ids,
            )
            conn.commit()
            return len(query_ids)

    # ── price_records ───────────────────────────────────────────

    def add_price_record(self, record: FlightPrice) -> int:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO price_records (query_id,airline,flight_no,aircraft,"
                " departure_time,arrival_time,departure_airport,arrival_airport,"
                " duration,stops,price,cabin_class,source,recorded_at,"
                " purchase_url,sub_class,seat_inventory,is_mock)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                record.query_id, record.airline, record.flight_no, record.aircraft,
                record.departure_time, record.arrival_time,
                record.departure_airport, record.arrival_airport,
                record.duration, record.stops or 0, record.price,
                record.cabin_class, record.source,
                record.recorded_at or datetime.now().isoformat(),
                record.purchase_url, record.sub_class,
                record.seat_inventory or 9,
                int(getattr(record, "is_mock", False)),
            )
            conn.commit()
            row = conn.execute("SELECT @@IDENTITY").fetchone()
            return int(row[0])

    def add_price_records_bulk(self, records: List[FlightPrice]) -> None:
        conn = self._get_conn()
        with self._lock:
            for r in records:
                conn.execute(
                    "INSERT INTO price_records (query_id,airline,flight_no,aircraft,"
                    " departure_time,arrival_time,departure_airport,arrival_airport,"
                    " duration,stops,price,cabin_class,source,recorded_at,"
                    " purchase_url,sub_class,seat_inventory,is_mock)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    r.query_id, r.airline, r.flight_no, r.aircraft,
                    r.departure_time, r.arrival_time,
                    r.departure_airport, r.arrival_airport,
                    r.duration, r.stops or 0, r.price, r.cabin_class,
                    r.source, r.recorded_at or datetime.now().isoformat(),
                    r.purchase_url, r.sub_class, r.seat_inventory or 9,
                    int(getattr(r, "is_mock", False)),
                )
            conn.commit()

    def get_price_records(self, query_id: int, limit: int = 100) -> List[FlightPrice]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM price_records WHERE query_id=? ORDER BY id DESC "
            "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY",
            query_id, limit,
        ).fetchall()
        return [self._to_flightprice(r) for r in rows]

    def get_daily_min_prices(self, query_id: int, real_only: bool = False,
                             limit: int = 365):
        conn = self._get_conn()
        sql = (
            "SELECT CAST(recorded_at AS DATE) AS day, MIN(price) AS min_price"
            " FROM price_records WHERE query_id=?"
            + (" AND is_mock=0" if real_only else "")
            + " GROUP BY CAST(recorded_at AS DATE) ORDER BY day"
            + " OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
        )
        rows = conn.execute(sql, query_id, limit).fetchall()
        return [(str(r[0]), float(r[1])) for r in rows]

    def get_daily_cheapest_records(self, query_id: int, limit: int = 365) -> List[FlightPrice]:
        conn = self._get_conn()
        rows = conn.execute(
            """WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY CAST(recorded_at AS DATE) ORDER BY price ASC
                ) AS rn
                FROM price_records WHERE query_id=?
            ) SELECT * FROM ranked WHERE rn=1 ORDER BY recorded_at
               OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY""",
            query_id, limit,
        ).fetchall()
        return [self._to_flightprice(r) for r in rows]

    def prune_expired_records(self, days_old: int = 45) -> int:
        conn = self._get_conn()
        with self._lock:
            cutoff = (datetime.now() - timedelta(days=days_old)).isoformat()
            cur = conn.execute(
                "DELETE FROM price_records WHERE recorded_at<?", cutoff
            )
            conn.commit()
            return cur.rowcount

    # ── price_alerts ───────────────────────────────────────────

    def add_alert(self, query_id: int, target_price: float,
                  notify_email: bool = True, notify_wechat: bool = False) -> int:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO price_alerts (query_id,target_price,is_active,"
                " notify_email,notify_wechat,created_at)"
                " VALUES (?,?,1,?,?,?)",
                query_id, target_price, int(notify_email), int(notify_wechat),
                datetime.now().isoformat(),
            )
            conn.commit()
            row = conn.execute("SELECT @@IDENTITY").fetchone()
            return int(row[0])

    def update_alert(self, alert_id: int, **kwargs) -> None:
        conn = self._get_conn()
        with self._lock:
            allowed = ("target_price", "is_active", "notify_email",
                        "notify_wechat", "last_triggered")
            for k, v in kwargs.items():
                if k not in allowed:
                    continue
                if isinstance(v, bool):
                    v = int(v)
                conn.execute(
                    f"UPDATE price_alerts SET {k}=? WHERE id=?", v, alert_id
                )
            conn.commit()

    def update_alert_triggered(self, alert_id: int, triggered_at: str) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE price_alerts SET last_triggered=? WHERE id=?",
                triggered_at, alert_id,
            )
            conn.commit()

    def delete_alert(self, alert_id: int) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.execute("DELETE FROM price_alerts WHERE id=?", alert_id)
            conn.commit()

    def get_alerts_for_query(self, query_id: int) -> List[PriceAlert]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM price_alerts WHERE query_id=?", query_id
        ).fetchall()
        return [PriceAlert(
            id=r.id, query_id=r.query_id, target_price=r.target_price,
            is_active=bool(r.is_active), notify_email=bool(r.notify_email),
            notify_wechat=bool(r.notify_wechat), created_at=r.created_at or "",
            last_triggered=r.last_triggered or "",
        ) for r in rows]

    def get_active_alerts(self) -> List[PriceAlert]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM price_alerts WHERE is_active=1"
        ).fetchall()
        return [PriceAlert(
            id=r.id, query_id=r.query_id, target_price=r.target_price,
            is_active=bool(r.is_active), notify_email=bool(r.notify_email),
            notify_wechat=bool(r.notify_wechat), created_at=r.created_at or "",
            last_triggered=r.last_triggered or "",
        ) for r in rows]

    def mark_alert_triggered(self, alert_id: int) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE price_alerts SET last_triggered=? WHERE id=?",
                datetime.now().isoformat(), alert_id,
            )
            conn.commit()

    # ── alert_history ───────────────────────────────────────────

    def add_alert_history(self, alert_id: Optional[int], query_id: int,
                          price: float, target_price: float,
                          airline: str = "", flight_no: str = "",
                          message: str = "") -> int:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO alert_history (alert_id,query_id,price,target_price,"
                " airline,flight_no,triggered_at,message)"
                " VALUES (?,?,?,?,?,?,?,?)",
                alert_id, query_id, price, target_price,
                airline, flight_no, datetime.now().isoformat(), message,
            )
            conn.commit()
            row = conn.execute("SELECT @@IDENTITY").fetchone()
            return int(row[0])

    def get_alert_history(self, alert_id: int = 0, limit: int = 100) -> List[AlertHistory]:
        conn = self._get_conn()
        if alert_id:
            rows = conn.execute(
                "SELECT * FROM alert_history WHERE alert_id=? ORDER BY id DESC "
                "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY",
                alert_id, limit,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alert_history ORDER BY id DESC "
                "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY",
                limit,
            ).fetchall()
        return [AlertHistory(
            id=r.id, alert_id=r.alert_id, query_id=r.query_id,
            price=r.price, target_price=r.target_price,
            airline=r.airline or "", flight_no=r.flight_no or "",
            triggered_at=r.triggered_at or "", message=r.message or "",
        ) for r in rows]

    def get_stats(self) -> dict:
        conn = self._get_conn()
        n_queries = conn.execute("SELECT COUNT(*) FROM search_queries").fetchone()[0]
        n_records = conn.execute("SELECT COUNT(*) FROM price_records").fetchone()[0]
        n_alerts  = conn.execute("SELECT COUNT(*) FROM price_alerts").fetchone()[0]
        n_hist    = conn.execute("SELECT COUNT(*) FROM alert_history").fetchone()[0]
        return {"queries": n_queries, "records": n_records,
                "alerts": n_alerts, "history": n_hist}


# ── Factory ──────────────────────────────────────────────────────
def create_db_from_config():
    """Return a Database instance based on ``config.DB_ENGINE``."""
    from config import DB_ENGINE
    if DB_ENGINE == "sqlserver":
        from config import DB_SERVER, DB_NAME
        return Database(server=DB_SERVER, database=DB_NAME)
    else:
        from config import DB_PATH
        from .database import Database as _SQLiteDB
        return _SQLiteDB(db_path=DB_PATH)


__all__ = ["Database", "create_db_from_config"]
