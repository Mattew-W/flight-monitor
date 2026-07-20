#!/usr/bin/env python3
"""
修复 is_mock 标记
规则：source 不在 ['ctrip_browser'] 中且当前 is_mock=0 的记录，更新为 is_mock=1
"""
import sqlite3
import sys

DB_PATH = r"D:\WORKbuddy1\航班监测\flight_monitor\flight_monitor.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 统计修复前状态
    cursor.execute("SELECT COUNT(*) FROM price_records WHERE is_mock=0")
    before = cursor.fetchone()[0]
    print(f"[修复前] is_mock=0 的记录数: {before}")

    # 执行修复：非 ctrip_browser 且 is_mock=0 → 改为 is_mock=1
    cursor.execute("""
        UPDATE price_records
        SET is_mock = 1
        WHERE source NOT IN ('ctrip_browser') AND is_mock = 0
    """)
    fixed_count = cursor.rowcount
    conn.commit()

    # 统计修复后状态
    cursor.execute("SELECT COUNT(*) FROM price_records WHERE is_mock=0")
    after = cursor.fetchone()[0]

    print(f"[修复后] is_mock=0 的记录数: {after}")
    print(f"[修复数] 更新为 is_mock=1 的记录数: {fixed_count}")

    # 按 source 分组统计
    cursor.execute("""
        SELECT source, COUNT(*), SUM(is_mock) 
        FROM price_records 
        GROUP BY source 
        ORDER BY COUNT(*) DESC
    """)
    print("\n按 source 分组统计 (source, 总数, mock数):")
    for row in cursor.fetchall():
        print(f"  {row[0]}: total={row[1]}, mock={row[2]}, real={row[1]-row[2]}")

    conn.close()
    print("\n✅ is_mock 标记修复完成")

if __name__ == "__main__":
    main()
