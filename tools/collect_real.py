"""
真实数据采集脚本 — 从携程浏览器爬取真实航班价格
写入 is_mock=0 的真实数据，供 ML 训练使用

用法:
  python collect_real.py              # 采集全部热门航线
  python collect_real.py -n 5         # 只采集前 5 条航线
  python collect_real.py -d 3.0       # 每次搜索间隔 3 秒
  python collect_real.py --monitor    # 同时设为监控查询 (is_monitoring=1)
  python collect_real.py --headed     # 有头浏览器模式（手动解决 CAPTCHA）
  python collect_real.py --fast       # 快速模式（页面复用 + 减少等待 + 并行）
  python collect_real.py --workers 4  # 快速模式下并行 worker 数量（默认 3）
"""
import sys
import os
import io
import asyncio
import time
import random
import logging
from datetime import datetime, timedelta

# 修复 Windows 编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flight_monitor"))

from config import DB_PATH, POPULAR_ROUTES
from core.database import Database
from core.models import SearchQuery
from datasources.ctrip_browser_source import CtripBrowserSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def check_captcha(page):
    """检测页面是否出现 CAPTCHA 验证码（支持手机端和电脑端）"""
    try:
        html = await page.content()
        captcha_indicators = [
            "验证码", "captcha", "滑块验证", "请完成安全验证",
            "slide", "验证通过", "geetick", "geetest",
            "请向右滑动", "拼图验证", "安全检测",
            # 电脑端特有
            "geetest_panel", "verify-slider", "slide-verify",
            "请拖动滑块", "点击按钮进行验证", "nc_1_n1z", "nc_1_wrapper",
        ]
        html_lower = html.lower()
        for indicator in captcha_indicators:
            if indicator.lower() in html_lower:
                return True
        return False
    except Exception:
        return False


async def wait_for_captcha_solve(page, timeout_sec=180):
    """自动或手动解决 CAPTCHA"""
    # 先尝试机器自动识别
    try:
        from core.captcha_solver import auto_solve_captcha, HAS_CV2
        if HAS_CV2:
            print("\n" + "="*55)
            print("  🤖 检测到安全验证，尝试机器自动识别...")
            print("="*55)
            
            success = await auto_solve_captcha(page, timeout_sec=20)
            if success:
                print("  ✅ 机器自动识别通过！")
                await asyncio.sleep(2)
                return True
            else:
                print("  ⚠️  机器识别失败，转为手动模式")
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Auto solve error: {e}")

    # 机器识别失败，转为手动
    print("\n" + "="*55)
    print("  ⚠️  请在浏览器窗口中手动完成验证")
    print("  验证通过后，程序将自动继续搜索和采集...")
    print("="*55)
    print("  （等待中，最长 3 分钟）\n")
    
    start = time.time()
    while time.time() - start < timeout_sec:
        await asyncio.sleep(3)
        if not await check_captcha(page):
            print("  ✅ 验证已通过，自动继续采集...")
            await asyncio.sleep(3)
            return True
        elapsed = int(time.time() - start)
        if elapsed % 15 == 0 and elapsed > 0:
            print(f"  ⏳ 等待手动验证中... ({elapsed}s / {timeout_sec}s)")
    
    print("  ❌ 等待超时，跳过此航线")
    return False


# ── 原始串行模式（兼容保留）────────────────────────────────────

async def async_collect_real_data(routes, db_path, delay_sec=2.0, set_monitoring=False, headed=False):
    """从携程浏览器爬取真实航班价格数据（异步版本 — 原始串行模式）"""
    if headed:
        os.environ["HEADED_MODE"] = "1"
        # 重新导入以应用新配置
        import importlib
        import core.browser_pool as bp
        importlib.reload(bp)

    db = Database(db_path)
    total = 0
    skipped = 0
    empty_streak = 0
    empty_abort = 3
    total_searches = len(routes) * 2
    captcha_solved_count = 0

    ctrip_src = CtripBrowserSource()
    if not ctrip_src.is_available():
        logger.error("CtripBrowserSource 不可用")
        db.close()
        return 0

    print(f"\n{'='*55}")
    print(f"  真实数据采集 | 航线: {len(routes)} -> {total_searches} 次搜索")
    print(f"  间隔: ~{delay_sec:.1f}s (预计耗时: {total_searches * (delay_sec + 25) / 60:.0f} 分钟)")
    print(f"  监控模式: {'是' if set_monitoring else '否'}")
    print(f"  浏览器模式: {'有头 (手动CAPTCHA)' if headed else '无头'}")
    print(f"{'='*55}\n")

    t0 = time.time()

    for i, route in enumerate(routes):
        dep = route["departure"]
        dst = route["destination"]
        lbl = route.get("label", "")

        for tag, delta in [("near", 7), ("far", 30)]:
            if empty_streak >= empty_abort:
                print(f"\n  [警告] 连续 {empty_streak} 次空结果 (可能 IP 被限流)，提前终止")
                db.close()
                return total

            fut = (datetime.now() + timedelta(days=delta)).strftime("%Y-%m-%d")

            q = SearchQuery(
                departure=dep, destination=dst, departure_date=fut,
                cabin_class="economy", trip_type="oneway",
                is_monitoring=set_monitoring,
                label=f"{lbl}({tag})" if lbl else f"{dep}->{dst}",
            )

            prices = []
            try:
                # 有头模式下，先打开携程首页让用户手动解决 CAPTCHA
                if headed:
                    from core.browser_pool import get_browser_pool
                    pool = await get_browser_pool()
                    page = await pool.new_page("ctrip")
                    if page is None:
                        print(f"  [{i+1}/{len(routes)}] {dep}->{dst} ({tag}): 无法创建页面")
                        skipped += 1
                        empty_streak += 1
                        continue
                    
                    try:
                        await page.goto("https://m.ctrip.com/html5/flight/swift/", wait_until="domcontentloaded", timeout=20000)
                        await page.wait_for_timeout(3000)
                        
                        if await check_captcha(page):
                            print(f"\n  [{i+1}/{len(routes)}] ⚠️ 首页出现安全验证")
                            solved = await wait_for_captcha_solve(page)
                            if not solved:
                                skipped += 1
                                empty_streak += 1
                                continue
                            captcha_solved_count += 1
                            await page.wait_for_timeout(2000)
                    finally:
                        await pool.close_page(page)
                
                prices = await ctrip_src.search_flights(q)
            except Exception as e:
                logger.warning(f"  {dep}->{dst} ({tag}): {e}")

            if prices:
                empty_streak = 0
                qid = db.add_query(q)
                q.id = qid
                for p in prices:
                    p.query_id = qid
                    p.is_mock = False
                db.add_price_records(prices)
                total += len(prices)
                print(f"  [{i+1}/{len(routes)}] {dep}->{dst} ({tag}): {len(prices)} 条价格")
            else:
                skipped += 1
                empty_streak += 1
                print(f"  [{i+1}/{len(routes)}] {dep}->{dst} ({tag}): 无结果")

            if delay_sec > 0:
                await asyncio.sleep(delay_sec + random.uniform(0, 2.0))

    elapsed = time.time() - t0
    print(f"\n{'='*55}")
    print(f"  完成: {total} 条真实价格 | {elapsed:.0f}s ({elapsed/60:.1f} 分钟)")
    print(f"  搜索: {total_searches - skipped}/{total_searches} 成功, {skipped} 次空结果")
    if headed:
        print(f"  CAPTCHA 手动解决次数: {captcha_solved_count}")
    print(f"{'='*55}")

    db.close()
    return total


# ── 快速模式：页面复用 + 并行 workers ────────────────────────────

async def _worker_fast(worker_id, pool, ctrip_src, queue, db_path, results_dict, delay_sec, page_timeout):
    """快速模式 worker：复用单个页面处理分配到的航线"""
    db = Database(db_path)
    total = 0
    skipped = 0
    
    # 每个 worker 创建一个页面并复用
    page = await pool.new_page("ctrip")
    if page is None:
        print(f"  [Worker-{worker_id}] 无法创建页面，退出")
        db.close()
        return
    
    try:
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            i, route, tag, delta = item
            dep = route["departure"]
            dst = route["destination"]
            lbl = route.get("label", "")
            
            fut = (datetime.now() + timedelta(days=delta)).strftime("%Y-%m-%d")
            q = SearchQuery(
                departure=dep, destination=dst, departure_date=fut,
                cabin_class="economy", trip_type="oneway",
                is_monitoring=False,
                label=f"{lbl}({tag})" if lbl else f"{dep}->{dst}",
            )
            
            prices = []
            try:
                # 快速模式：使用更短的超时（10s 页面加载 + 2s 等待）
                prices = await ctrip_src.search_flights_with_page(
                    page, q, page_timeout_ms=10000, wait_after_load_ms=2000
                )
            except Exception as e:
                logger.warning(f"  [Worker-{worker_id}] {dep}->{dst} ({tag}): {e}")
            
            if prices:
                qid = db.add_query(q)
                q.id = qid
                for p in prices:
                    p.query_id = qid
                    p.is_mock = False
                db.add_price_records(prices)
                total += len(prices)
                print(f"  [W-{worker_id}] [{i+1}] {dep}->{dst} ({tag}): {len(prices)} 条")
            else:
                skipped += 1
                print(f"  [W-{worker_id}] [{i+1}] {dep}->{dst} ({tag}): 无结果")
            
            results_dict["total"] = results_dict.get("total", 0) + len(prices)
            results_dict["skipped"] = results_dict.get("skipped", 0) + (1 if not prices else 0)
            
            if delay_sec > 0:
                await asyncio.sleep(delay_sec + random.uniform(0, 1.0))
    
    finally:
        await pool.close_page(page)
        db.close()


async def async_collect_real_data_fast(routes, db_path, delay_sec=1.0, set_monitoring=False, 
                                       headed=False, workers=3):
    """快速模式：页面复用 + 多 worker 并行 + 减少等待时间"""
    if headed:
        os.environ["HEADED_MODE"] = "1"
        import importlib
        import core.browser_pool as bp
        importlib.reload(bp)

    total_searches = len(routes) * 2
    
    print(f"\n{'='*60}")
    print(f"  真实数据采集 | ⚡ 快速模式")
    print(f"  航线: {len(routes)} -> {total_searches} 次搜索")
    print(f"  Workers: {workers} 并行 | 间隔: ~{delay_sec:.1f}s")
    print(f"  预计耗时: {total_searches * (delay_sec + 8) / workers / 60:.0f} 分钟")
    print(f"  浏览器模式: {'有头 (手动CAPTCHA)' if headed else '无头'}")
    print(f"  优化: 页面复用 + 减少等待 + 并行搜索")
    print(f"{'='*60}\n")

    from core.browser_pool import get_browser_pool
    pool = await get_browser_pool()
    
    # 有头模式：只检查一次验证码
    if headed:
        print("  🖥️  有头模式：首次检查验证码...")
        page = await pool.new_page("ctrip")
        if page is None:
            print("  ❌ 无法创建页面")
            return 0
        try:
            await page.goto("https://m.ctrip.com/html5/flight/swift/", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            if await check_captcha(page):
                print("  ⚠️ 检测到安全验证，请手动解决...")
                solved = await wait_for_captcha_solve(page)
                if not solved:
                    print("  ❌ 验证失败，退出")
                    return 0
                print("  ✅ 验证通过，后续搜索将复用 session")
            else:
                print("  ✅ 无需验证，直接开始采集")
        finally:
            await pool.close_page(page)

    # 构建任务队列
    queue = asyncio.Queue()
    for i, route in enumerate(routes):
        for tag, delta in [("near", 7), ("far", 30)]:
            queue.put_nowait((i, route, tag, delta))

    ctrip_src = CtripBrowserSource()
    if not ctrip_src.is_available():
        logger.error("CtripBrowserSource 不可用")
        return 0

    t0 = time.time()
    results_dict = {}
    
    # 启动多个 worker 并行
    worker_tasks = []
    for wid in range(workers):
        task = asyncio.create_task(
            _worker_fast(wid, pool, ctrip_src, queue, db_path, results_dict, delay_sec, 10000)
        )
        worker_tasks.append(task)
    
    # 等待所有 worker 完成
    await asyncio.gather(*worker_tasks)
    
    elapsed = time.time() - t0
    total = results_dict.get("total", 0)
    skipped = results_dict.get("skipped", 0)
    
    print(f"\n{'='*60}")
    print(f"  ⚡ 快速模式完成: {total} 条真实价格 | {elapsed:.0f}s ({elapsed/60:.1f} 分钟)")
    print(f"  搜索: {total_searches - skipped}/{total_searches} 成功, {skipped} 次空结果")
    print(f"  平均速度: {elapsed / total_searches:.1f}s/搜索 (vs 原始 ~30s/搜索)")
    print(f"{'='*60}")
    
    return total


def set_monitoring_queries(db_path):
    """将部分查询设为 is_monitoring=1，让后台监控自动爬取"""
    db = Database(db_path)
    conn = db._get_conn()

    # 选取几条热门航线设为监控
    monitoring_routes = [
        ("北京", "上海"),
        ("北京", "广州"),
        ("上海", "深圳"),
    ]

    count = 0
    for dep, dst in monitoring_routes:
        # 查找对应的 query
        rows = conn.execute(
            "SELECT id FROM search_queries WHERE departure=? AND destination=? AND is_monitoring=0 LIMIT 1",
            (dep, dst)
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE search_queries SET is_monitoring=1 WHERE id=?",
                (row[0],)
            )
            count += 1
            print(f"  设置监控: {dep}->{dst} (id={row[0]})")

    conn.commit()
    db.close()
    print(f"  共设置 {count} 条监控查询")
    return count


def generate_city_matrix(cities: list) -> list:
    """生成城市全矩阵航线（每对城市 A->B 和 B->A）"""
    routes = []
    for i, dep in enumerate(cities):
        for j, arr in enumerate(cities):
            if i != j:
                routes.append({
                    "departure": dep,
                    "destination": arr,
                    "label": f"{dep}-{arr}",
                })
    return routes


def main():
    import argparse
    p = argparse.ArgumentParser(description="真实数据采集 (Ctrip 浏览器爬取)")
    p.add_argument("-n", "--limit", type=int, default=5,
                   help="只采集前 N 条热门航线 (默认 5)")
    p.add_argument("-d", "--delay", type=float, default=2.0,
                   help="搜索间隔秒数 (默认 2.0)")
    p.add_argument("--monitor", action="store_true",
                   help="同时设为监控查询 (is_monitoring=1)")
    p.add_argument("--set-monitoring-only", action="store_true",
                   help="只设置监控查询，不采集数据")
    p.add_argument("--headed", action="store_true",
                   help="有头浏览器模式（遇到 CAPTCHA 时手动解决/自动识别）")
    p.add_argument("--full-matrix", action="store_true",
                   help="核心城市全矩阵模式（20城市x19=380条航线）")
    p.add_argument("--all-cities", action="store_true",
                   help="全部国内城市全矩阵（60+城市，3500+条航线，耗时极长）")
    p.add_argument("--cities", type=str, default=None,
                   help="指定城市列表，逗号分隔（如: 北京,上海,广州,成都）")
    p.add_argument("--fast", action="store_true",
                   help="快速模式：页面复用 + 并行 workers + 减少等待")
    p.add_argument("--workers", type=int, default=3,
                   help="快速模式并行 worker 数量 (默认 3)")
    args = p.parse_args()

    # 确定航线列表
    if args.full_matrix:
        # 核心 20 城市全矩阵
        core_cities = [
            "北京", "上海", "广州", "深圳", "成都", "杭州", "武汉", "西安",
            "重庆", "南京", "长沙", "昆明", "厦门", "大连", "天津", "郑州",
            "三亚", "哈尔滨", "沈阳", "贵阳"
        ]
        routes = generate_city_matrix(core_cities)
        print(f"\n  核心城市全矩阵: {len(core_cities)} 城市 -> {len(routes)} 条航线")
    elif args.all_cities:
        # 全部国内城市
        from config import CITY_CODES
        domestic = [c for c in CITY_CODES if not c in ("香港", "澳门", "台北", "高雄")]
        routes = generate_city_matrix(domestic)
        print(f"\n  全部城市全矩阵: {len(domestic)} 城市 -> {len(routes)} 条航线")
        print(f"  警告: 这将产生 {len(routes) * 2} 次搜索，可能需要数天!")
    elif args.cities:
        # 指定城市
        city_list = [c.strip() for c in args.cities.split(",")]
        routes = generate_city_matrix(city_list)
        print(f"\n  指定城市矩阵: {len(city_list)} 城市 -> {len(routes)} 条航线")
    else:
        # 默认：预定义热门航线
        routes = POPULAR_ROUTES[:args.limit]
        print(f"\n  热门航线: {len(routes)} 条")

    if args.set_monitoring_only:
        print("\n  只设置监控查询模式")
        set_monitoring_queries(DB_PATH)
        return

    if args.headed:
        print("\n  🖥️  有头浏览器模式已启用")
        print("  首次打开时会弹出浏览器窗口，请手动完成 CAPTCHA 验证")
        print("  验证通过后程序将自动继续采集\n")

    # 采集真实数据
    if args.fast:
        # 快速模式
        total = asyncio.run(async_collect_real_data_fast(
            routes, DB_PATH, delay_sec=max(args.delay, 0.5),
            set_monitoring=args.monitor, headed=args.headed,
            workers=args.workers
        ))
    else:
        # 原始串行模式
        total = asyncio.run(async_collect_real_data(
            routes, DB_PATH, delay_sec=args.delay,
            set_monitoring=args.monitor, headed=args.headed
        ))

    # 如果带了 --monitor，同时确保有监控查询
    if args.monitor:
        print("\n  确保监控查询已设置...")
        set_monitoring_queries(DB_PATH)

    # 验证
    if total > 0:
        db = Database(DB_PATH)
        conn = db._get_conn()
        real_count = conn.execute("SELECT COUNT(*) FROM price_records WHERE is_mock=0").fetchone()[0]
        print(f"\n  数据库中真实数据总量: {real_count} 条")
        db.close()


if __name__ == "__main__":
    main()
