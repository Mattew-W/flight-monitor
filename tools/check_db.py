# -*- coding: utf-8 -*-
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import Database
db = Database('flight_monitor.db')
conn = db._get_conn()

# Check real data (is_mock=0)
print("Real data (is_mock=0) per query:")
rows = conn.execute('''
    SELECT q.id, q.departure, q.destination, COUNT(pr.id) as cnt
    FROM search_queries q
    LEFT JOIN price_records pr ON q.id = pr.query_id AND pr.is_mock = 0
    GROUP BY q.id
    HAVING cnt > 0
    ORDER BY cnt DESC
    LIMIT 10
''').fetchall()
for r in rows:
    print(f'  id={r["id"]}, {r["departure"]} -> {r["destination"]}, real_records={r["cnt"]}')

# Check mock data
print("\nMock data (is_mock=1) per query:")
rows2 = conn.execute('''
    SELECT q.id, q.departure, q.destination, COUNT(pr.id) as cnt
    FROM search_queries q
    LEFT JOIN price_records pr ON q.id = pr.query_id AND pr.is_mock = 1
    GROUP BY q.id
    HAVING cnt > 0
    ORDER BY cnt DESC
    LIMIT 5
''').fetchall()
for r in rows2:
    print(f'  id={r["id"]}, {r["departure"]} -> {r["destination"]}, mock_records={r["cnt"]}')

# Check BJS->SHA specifically
print("\nBJS->SHA queries:")
rows3 = conn.execute("SELECT id, departure, destination FROM search_queries WHERE departure LIKE '%北京%' AND destination LIKE '%上海%'").fetchall()
for r in rows3:
    print(f'  id={r["id"]}, {r["departure"]} -> {r["destination"]}')
    # Count real prices
    cnt = conn.execute("SELECT COUNT(*) as c FROM price_records WHERE query_id=? AND is_mock=0", (r["id"],)).fetchone()
    print(f'    real prices: {cnt["c"]}')
    cnt2 = conn.execute("SELECT COUNT(*) as c FROM price_records WHERE query_id=? AND is_mock=1", (r["id"],)).fetchone()
    print(f'    mock prices: {cnt2["c"]}')
