"""
SQLite → SQL Server LocalDB 迁移脚本
========================================
将现有 flight_monitor.db 里的数据迁移到新 .mdf 文件。

使用方法：
    1. 安装 LocalDB、pyodbc
    2. 确保 config.py 中 DB_ENGINE='sqlserver'（或环境变量）
    3. 运行迁移：  python tools/migrate_sqlite_to_localdb.py
    4. 迁移完成后，改回 DB_ENGINE=sqlite 不影响现有代码
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def migrate():
    from config import DB_PATH, DB_FILE, DB_SERVER
    from core.database_sqlserver import Database as SqlServerDB
    from core.database import Database as SqliteDB
    from core.models import FlightPrice, SearchQuery

    if not os.path.exists(DB_PATH):
        print(f"[ERROR] SQLite DB not found: {DB_PATH}")
        return

    print("[1/4] Reading SQLite data...")
    sqlite = SqliteDB(DB_PATH)

    queries = sqlite.get_all_queries()
    print(f"  - {len(queries)} search_queries")

    alerts = []
    for q in queries:
        alerts.extend(sqlite.get_alerts_for_query(q.id))
    print(f"  - {len(alerts)} price_alerts")

    records = []
    for q in queries:
        records.extend(sqlite.get_price_records(q.id, limit=10000))
    print(f"  - {len(records)} price_records")

    histories = sqlite.get_alert_history(limit=10000)
    print(f"  - {len(histories)} alert_history")

    print("\n[2/4] Creating LocalDB database...")
    mssql = SqlServerDB(mdf_path=DB_FILE, server=DB_SERVER)

    print("[3/4] Writing data to LocalDB...")
    for q in queries:
        mssql.add_query(
            q.departure, q.destination, q.departure_date,
            q.cabin_class, q.trip_type, q.return_date, q.label,
        )

    # Get new query IDs (IDENTITY)
    mssql_queries = mssql.get_all_queries()
    id_map = {}
    for old_q in queries:
        for new_q in mssql_queries:
            if (new_q.departure == old_q.departure and
                new_q.destination == old_q.destination and
                new_q.departure_date == old_q.departure_date and
                new_q.created_at == old_q.created_at):
                id_map[old_q.id] = new_q.id
                break

    print(f"  - Mapped {len(id_map)} query IDs")

    for r in records:
        new_qid = id_map.get(r.query_id, r.query_id)
        mssql.add_price_record(FlightPrice(
            query_id=new_qid, airline=r.airline, flight_no=r.flight_no,
            aircraft=r.aircraft, departure_time=r.departure_time,
            arrival_time=r.arrival_time, departure_airport=r.departure_airport,
            arrival_airport=r.arrival_airport, duration=r.duration,
            stops=r.stops, price=r.price, cabin_class=r.cabin_class,
            source=r.source, recorded_at=r.recorded_at,
            purchase_url=r.purchase_url,
        ))

    for a in alerts:
        new_qid = id_map.get(a.query_id, a.query_id)
        mssql.add_alert(new_qid, a.target_price, a.notify_email, a.notify_wechat)

    print("[4/4] Migration complete!")
    stats = mssql.get_stats()
    print(f"  Final: {stats}")
    mssql.close_all()
    sqlite.close_all()

if __name__ == "__main__":
    migrate()
