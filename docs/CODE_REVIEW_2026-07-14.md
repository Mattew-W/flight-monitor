# 航班监测项目代码审查报告

**审查日期**：2026-07-14
**审查范围**：`flight_monitor/` 全部 38 个源 Python 文件（约 12,000 行）
**审查方式**：4 个并行子代理 + 主代理复核（已验证全部 P0 真实存在）

| 级别 | 数量 | 含义 |
|------|------|------|
| **P0** | 6 | 阻断性 bug / 安全漏洞 — 必须立即修复 |
| **P1** | 14 | 严重缺陷 / 数据失真 — 本周内修复 |
| **P2** | 16 | 一般问题 / 资源泄漏 — 排期修复 |
| **P3** | 15 | 代码质量 / 可维护性 — 顺手改进 |

---

## P0 — 阻断性 Bug（已逐条复核源码确认）

### P0-1 `core/notifier.py:88` — 邮件正文传入 `html` 模块对象，而非 HTML 内容
```python
import html                      # 第 7 行
...
html_content = f"""..."""        # 第 74 行 生成正确变量
msg.attach(MIMEText(html, "html", "utf-8"))   # 第 88 行 ✅ 传入的是模块！
```
**后果**：每封降价提醒邮件正文为 `<module 'html' from 'C:\\...\\html.py'>`，邮件功能完全失效但 `sendmail` 不报错（因为字符串本身可发送），`logger.info("Email notification sent")` 误导排查。
**修复**：第 88 行改为 `msg.attach(MIMEText(html_content, "html", "utf-8"))`。

### P0-2 `api/routes.py:530-533` — 死代码引用未定义变量
```python
except Exception as e:
    return jsonify({"found": False, "error": str(e)}), 500   # 第 529 行已 return
    sched["found"] = True                                     # 第 530 行 sched 未定义
    sched["flight_no"] = flight_no.upper()                    # 第 531 行 flight_no 未定义
    return jsonify(sched)                                     # 第 532 行
return jsonify({"found": False, "flight_no": flight_no.upper()})  # 第 533 行
```
**成因**：从 `flight_lookup`（行 440-445）复制粘贴后未清理。
**修复**：删除第 530-533 行。同时第 529 行 `str(e)` 直接回客户端会泄露内部异常/堆栈路径，改为 `{"error": "外部接口调用失败"}` + `logger.exception(e)`。

### P0-3 `core/browser_pool.py:85-87` — 空闲回收正在使用的 context
```python
if self._browser and (now - self._last_used) > _IDLE_TIMEOUT:
    logger.info("BrowserPool: idle timeout, recycling all contexts")
    self._close_internal()    # ⚠ 未检查 self._refcount
```
**后果**：线程 A 持有 context 跑耗时爬取（>180s），线程 B 进入 acquire 触发空闲回收，A 正在使用的 context 被关闭 → A 后续操作崩溃。
**修复**：`if (now - self._last_used) > _IDLE_TIMEOUT and self._refcount == 0:`

### P0-4 `core/browser_pool.py:116-121` — Playwright sync API 多线程并发崩溃
```python
def new_page(self, platform: str = "default"):
    ctx = self.acquire(platform)   # 锁内取 context
    if ctx is None: return None
    return ctx.new_page()          # ⚠ 锁外调用，多线程并发操作同一 context
```
**后果**：`monitor.py:157` 的 `ThreadPoolExecutor` 多 worker 并发调用时，同一 platform 的 context 被并发 `new_page()`，Playwright Python sync_api **不是线程安全**的，会抛 `greenlet.error` 或 `SyncAPIError`。
**修复方案三选一**：
- 改用 `async_api` + 单事件循环（推荐）
- `new_page` 全程持锁（牺牲并发，简单）
- 每次 `new_page` 创建独立 context（资源开销大）

### P0-5 `transfer_prices.py:13-86` — 整脚本在模块层执行，`import` 即触发 DB 写
```python
db = Database(DB_PATH)           # 第 13 行 模块顶层
conn = db._get_conn()            # 第 14 行
rows = conn.execute(...)         # 第 17 行 立即执行
...
conn.commit()                    # 第 81 行 写入
db.close()                       # 第 86 行
```
**后果**：任何 `import transfer_prices`（如未来某模块加 `from transfer_prices import ...`，或 pytest 收集）都会向数据库插入迁移数据。
**修复**：包进 `def main(): ...` 并加 `if __name__ == "__main__": main()` 守卫。

### P0-6 `api/routes.py` 全文（23 个端点） — 完全无认证 / 无 CORS / 无限流
所有端点零鉴权：`DELETE /api/queries/<id>`、`POST /api/queries/<id>/search`（触发爬虫）、`POST /api/monitor/start|stop`（控制守护进程）、`POST /api/queries/bulk-delete` 任意人可调。无 CORS 配置，无任何中间件。

`search_now`（行 185-199）与 `flight_live_price`（行 459-529）触发昂贵外部调用却无速率限制，攻击者可循环调用导致出口 IP 被 Ctrip 封禁、爬虫线程池耗尽。

**修复**：
- 加 Flask-Login / API Key 装饰器，敏感写操作强制鉴权
- 用 flask-cors 显式白名单
- 用 Flask-Limiter 限制（如 `search_now` 每 IP 每分钟 5 次）

---

## P1 — 严重缺陷

### P1-1 `core/database.py:146, 182, 333, 359, 368, 373, 379` — 单条写操作无 try/except/rollback
`update_query_monitoring`、`add_price_record`、`add_alert`、`update_alert`、`delete_alert`、`mark_alert_triggered`、`add_alert_history` 均无 rollback 保护。
**后果**：Python sqlite3 默认 `isolation_level=''` 会隐式开启事务。若 `execute` 抛异常（约束冲突等），连接停留在未提交事务；该线程后续调用 `delete_query`（行 154 `conn.execute("BEGIN")`）会抛 `cannot start a transaction within a transaction`。
**修复**：所有写操作包裹 `try/except/conn.rollback()`。注意 `add_price_records`、`delete_query`、`delete_queries_bulk` 已有正确模板，可复用。

### P1-2 `core/database.py:42-50` — `close()` 仅关闭当前线程连接，其余线程连接泄漏
`_get_conn()` 返回 thread-local 连接，`close()` 通过 `_get_conn()` 拿到的只是调用线程的连接。monitor 后台线程 / Flask 请求线程的连接不会被关闭。无 `close_all()` 方法。
**修复**：维护 `_conns` 注册表（weakref.WeakSet），`close_all()` 遍历关闭；在 `main.py:finally` 中调用。

### P1-3 `core/monitor.py:121-130` — `start()/stop()` 存在 TOCTOU
`if self._running: return` 与 `self._running = True` 之间无锁，并发调用可启动两个监控线程。
**修复**：用 `self._lock` 保护 `_running` 状态变更（注意不要与 db._lock 混用）。

### P1-4 `core/monitor.py:178, 205, 211, 253` — price 为 None / NaN 时崩溃
```python
min(p.price for p in prices)              # 行 178
p.price < alert.target_price              # 行 205/211
sort(key=lambda p: p.price)               # 行 253
```
**后果**：数据源返回 `FlightPrice(price=None)` 或 `price=NaN` 时抛 `TypeError`，该 query 的告警检查整体失败。
**修复**：`min((p.price for p in prices if p.price is not None and p.price == p.price), default=None)`，并跳过 None。

### P1-5 `core/monitor.py:52-62` — `stop()` 丢弃队列中待发通知
```python
def stop(self):
    self._running = False
    while True:                            # 先排空队列
        self._queue.get_nowait()
        self._queue.task_done()
    for t in self._workers: t.join(timeout=3)
```
**后果**：已触发但未发送的降价提醒被静默丢弃，用户丢失关键告警。
**修复**：调换顺序 — 先 `_running=False`，再 `join` worker 让其处理完剩余队列（带超时），最后强制退出。

### P1-6 `core/price_prediction.py:354, 497, 742` — `hash(profile)` 跨进程不可复现
```python
rng = random.Random(int(current_price * 1000 + hash(profile)) % 2**31)
```
Python 内置 `hash(str)` 受 `PYTHONHASHSEED` 影响，每次启动结果不同。
**后果**：同一航线合成历史每次都变，图表抖动、ML 特征不稳。`ml_predictor.py:202` 已正确示范用 `hashlib.md5`。
**修复**：
```python
import hashlib
seed = int(hashlib.md5(profile.encode()).hexdigest()[:8], 16)
rng = random.Random(int(current_price * 1000 + seed) % 2**31)
```

### P1-7 `core/session_manager.py:68-78` — `cryptography` 未装时 XOR "加密"等同明文
`_xor_encrypt` 使用单字节循环 XOR，密钥固定且已知（SHA256 派生）。会话 Cookie（含登录态）以近乎明文形式落盘。
**修复**：强制 `cryptography` 为必需依赖；或至少用 `hashlib.pbkdf2_hmac` 派生密钥 + 标准 AES，并明确标注"不安全"。

### P1-8 `core/notifier.py:38-55` — 通知无去重 / 无限流，必然刷屏
`send_notification` 每次调用即向线程池提交三个渠道发送任务。监测器每 5 分钟轮询（`config.py:17`），价格持续变动时用户被邮件 + 飞书 + Server酱三路轰炸。
**修复**：引入 `(query_id, price_band)` 维度去重缓存与最小通知间隔（如 1 小时 / 天 N 条上限）。

### P1-9 `core/notifier.py:113, 133` — webhook URL / Server酱 key 可能随异常泄漏到日志
```python
except Exception as e:
    logger.error(f"Failed to send WeChat notification: {e}")
```
`requests` 异常的 `str(e)` 常包含完整 URL（含密钥）。
**修复**：异常日志只记 `type(e).__name__` + 脱敏消息，或对 URL 做 `re.sub` 脱敏（隐藏 path 段）。

### P1-10 `core/ml_predictor.py:725-734` — 置信区间 clamp 后可能 lower > upper
```python
lower[i] = max(orig_lower, 0.7 * forecast)   # 如 orig_lower=0.6f → 0.7f
upper[i] = min(orig_upper, 1.4 * forecast)   # 如 orig_upper=0.65f → 0.65f
```
当 bootstrap 区间窄于 0.7f~1.4f 时，区间倒挂。
**修复**：clamp 后强制 `lower[i] = min(lower[i], upper[i])`。

### P1-11 `datasources/multi_airline_scraper.py:267-270` — Trip.com URL 用中文城市名拼接
```python
purchase_url = f"https://www.trip.com/flights/{query.departure}-{query.destination}/?ddate=..."
# query.departure = "北京" → URL 无效
```
Trip.com 实际使用 IATA 码（BJS-SHA）。
**修复**：使用已查到的 `dep_code` / `arr_code` 拼接。

### P1-12 `datasources/multi_platform_scraper.py:132-148` — 提取的 FlightPrice 大量字段为空
正则只提取 `flight_no` 和 `price`，`airline`、`departure_time`、`aircraft`、`duration` 全部为空。下游无法按航司/时间分析。
**修复**：补充正则提取航司名、起降时间；或走 API 拦截而非 DOM 正则。

### P1-13 `datasources/mock_source.py:539` vs `ctrip_browser_source.py:119` — source 标识不一致
Mock 用 `source="ctrip"`，真实爬虫用 `source="ctrip_browser"`。同一条航线在 mock/real 切换时 source 不匹配，导致去重、比价、历史追踪逻辑可能断裂。
**修复**：统一 source 命名规范，mock 用 `"mock_ctrip"`，真实用 `"ctrip"`。

### P1-14 `api/routes.py:180, 361` — `request.json` 非 silent，非 JSON body 直接 500
```python
data = request.json           # 无 Content-Type: application/json 抛 415
                             # 空 body 后续 data.get 抛 AttributeError
```
**修复**：统一改 `request.get_json(silent=True) or {}` 并校验非空（参考行 552 的正确写法）。

---

## P2 — 一般问题（精选）

| # | 文件:行号 | 问题 |
|---|-----------|------|
| P2-1 | `database.py:32` | `check_same_thread=False` 多余且降低安全性（已 thread-local，该参数绕过 sqlite3 线程安全校验） |
| P2-2 | `database.py:295-305` | `get_all_latest_prices` 同时间戳多记录返回重复，应用窗口函数或 `batch_id` 去重 |
| P2-3 | `database.py:317-329` | `get_all_prices_for_export` 无分页，全表加载 OOM 风险 |
| P2-4 | `browser_pool.py:116-121` | `new_page` 异常时 refcount 泄漏（acquire 已 +1，但无 finally release） |
| P2-5 | `session_manager.py:100-111` | save 非原子写入，进程崩溃则文件损坏；应用临时文件 + `os.replace` |
| P2-6 | `ctrip_browser_source.py:690-691` | `__del__` 调用 `close()` 有死锁风险，应删除改显式 close |
| P2-7 | `ctrip_browser_source.py:482-483` | 时间解析对 ISO 格式产出错误（`"2024-01-01T10:00:00"` → `"2024-"`） |
| P2-8 | `multi_airline_scraper.py:93-125` | interceptor 固定等待全量超时（15s），应用 `wait_for_response` 事件驱动 |
| P2-9 | `airline_sniffer.py:204` | `int(stops)` 对 `"1 站"` 等非纯数字字符串抛 ValueError 未捕获 |
| P2-10 | `airline_sniffer.py:256-279` | 每次搜索新建浏览器，冷启动 3-5 秒/次；应复用浏览器池 |
| P2-11 | `routes.py:84-85, 227` | `limit` / `offset` 无边界校验，可传负数或 999999 |
| P2-12 | `routes.py:150-159` | `cabin_class` / `trip_type` / 城市码无白名单校验直接落库 |
| P2-13 | `routes.py:169-176` | `bulk_delete` 无上限 + `int(i)` 可抛 ValueError |
| P2-14 | `routes.py:267-309` | `export_data` 无分页，全量 CSV 写入内存 |
| P2-15 | `price_prediction.py:818 vs 993` | `drop_pct` 分母不一致（current vs predicted_min） |
| P2-16 | `ml_predictor.py:457-508` | `_RidgeLinear` 数学错误（标准化与 intercept 未联合优化，预测系统性偏置） |

**爬虫层严重代码重复**（应抽公共模块）：
- 浏览器启动参数在 4 个文件中重复
- 城市映射在 5 处重复
- 航司配置在 `multi_airline_scraper.AIRLINE_CONFIG` 和 `airline_sniffer.AIRLINE_CONFIGS` 中重复定义
- JSON 拦截回调模式在 3 个文件中重复实现

---

## P3 — 代码质量（精选）

- `aggregator.py:99-313` — `process_search_results` 单函数 214 行，应拆 5-6 个私有方法
- `aggregator.py:183` — `except (KeyError, Exception)` 中 `KeyError` 冗余
- `monitor.py:229-236` — `alert.id or 0` 模式：若 id 为 None 则更新不存在的行静默失败
- `models.py:28, 38, 66` — `price: float = 0.0` 无校验，建议 `__post_init__` 校验 `price >= 0`
- `database.py:319, 347` — `if query_id:` 对 `query_id=0` 为 falsy，应改 `is not None`
- `routes.py:417` — 访问私有属性 `monitor._running`，应暴露 `is_running` 属性
- `routes.py:439, 453` — `ImportError` 返回 500，应为 501 Not Implemented
- `routes.py:全文` — 23 个端点无一处 `logger.info` 记录请求，except 块也无 `logger.exception`，排障困难
- `routes.py:459` — `flight_live_price` 用 GET 调外部 API 改变 Ctrip 侧计数，应改 POST
- `price_prediction.py:145` — 函数内 `from config import CITY_CODES` 无 try/except，ImportError 直接崩溃
- `price_prediction.py:45-60` vs `ml_predictor.py:88-96` — `_HOLIDAY_RULES` 重复定义，且春节等农历节日用固定公历锚点逐年失准
- `config.py:281-544` — 城市码 / 航司 / 航线 / 区域全量硬编码 ~250 行，应迁到 JSON/YAML
- `config.py:261` — `"土耳其航空": "qatar"` 错误映射；config 中 `thai` 与 `thaiairways` 两个 key 重复定义泰国航空
- `notifier.py:57-60` — `__del__` 关闭线程池不可靠，应提供显式 `close()` + contextmanager
- `base.py` — `BaseDataSource` 缺少 `close()` 抽象方法

---

## 修复优先级建议

### 第一波（本周必修，影响功能正确性）
1. **P0-1** notifier.py:88 一行修复 → 邮件功能恢复
2. **P0-2** routes.py:530-533 删 4 行 + 改异常返回
3. **P0-3** browser_pool.py:85 加 `and self._refcount == 0`
4. **P0-5** transfer_prices.py 包 `__main__` 守卫
5. **P1-1** database.py 7 处写操作加 try/except/rollback
6. **P1-4** monitor.py price None 校验
7. **P1-6** price_prediction.py hash → hashlib.md5（3 处）

### 第二波（下周，影响安全 / 资源）
8. **P0-6** routes.py 加 Auth + Limiter 中间件
9. **P0-4** browser_pool 多线程方案（async_api 改造或全程持锁）
10. **P1-2** database.py 加 `close_all()` + main.py 调用
11. **P1-5** monitor.py stop() 调换 join/drain 顺序
12. **P1-8/9** notifier 去重 + 日志脱敏

### 第三波（排期，代码质量）
13. P1-10 ~ P1-14
14. P2 全部
15. P3 顺手改进

---

## 整体评价

**优点**：
- 架构分层清晰（`core/` / `api/` / `datasources/`），数据流（爬虫 → 聚合 → DB → API → 前端）合理
- 数据库已用 WAL + RLock + 事务删除（用户 7-14 重构成果），核心批量写正确
- 合成数据诚实标注（`is_mock=1` / `is_synthetic`），ML 训练严格用真实数据
- 配置外置到 `config.py`，凭证支持 env 注入
- 主入口 `main.py` 简洁，有 finally 清理

**主要风险**：
- **API 安全裸奔**（P0-6）：本地开发可，一旦暴露公网即灾难
- **Playwright 多线程不安全**（P0-3/4）：monitor 并发轮询时会偶发崩溃
- **写操作 rollback 不全**（P1-1）：长期运行下连接会卡在事务态
- **通知刷屏 + 邮件失效**（P0-1 + P1-8）：用户实际上收不到正确的降价提醒
- **代码重复严重**：4 个爬虫文件大量重复，维护成本高

**项目健康度评分**：6.5 / 10
- 架构设计：7.5
- 功能完整度：7.0
- 安全性：4.0（裸奔 API + 凭证管理薄弱）
- 健壮性：5.5（多处 None/异常未处理）
- 可维护性：6.0（代码重复 + 长函数）
- 文档与测试：5.5（README 完善，但无单元测试）
