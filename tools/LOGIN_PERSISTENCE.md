"""
Flight Monitor - One-Time Login & Session Persistence
=====================================================

设计目标：
  用户只需在浏览器里扫码/输密码登录一次，所有数据源后续都能用同一份 Cookie
  抓取携程、去哪儿、飞猪、同程、航司官网等平台的数据，避免每次爬虫都触发
  反爬/要求登录。

持久化方案（推荐）
--------------------

每个平台存一个独立的 JSON 文件到 `sessions/` 目录：

  sessions/
    ctrip.json          # 携程
    qunar.json          # 去哪儿
    fliggy.json         # 飞猪
    tongcheng.json      # 同程
    airchina.json       # 国航
    ...

每个文件结构：
  {
    "platform": "ctrip",
    "user_id": "...",          # 可选，登录后填入
    "logged_in_at": "2026-07-14T08:30:00",
    "expires_at": "2026-07-21T08:30:00",  # 软过期 7 天
    "cookies": [
        {"name": "uuid", "value": "xxx", "domain": ".ctrip.com", "path": "/", ...},
        ...
    ],
    "user_agent": "...",
    "viewport": {"width": 375, "height": 812},
  }

技术实现流程
-----------

[一次性] 用户运行：
    python tools/login.py ctrip
      ↓
    1. BrowserPool 启动有头(headless=False) Chrome
    2. 导航到 https://m.ctrip.com/html5/flight/swift/
    3. Playwright 打开登录页，等待用户：
       - 扫码（首选）
       - 短信验证
       - 账号密码
    4. 监听 URL 变化，登录成功跳转到首页
    5. 调用 page.context.cookies() 拿到所有 Cookie
    6. 保存到 sessions/ctrip.json

[持续] 数据源运行时：
    CtripBrowserSource 启动
      ↓
    1. 检查 sessions/ctrip.json 是否存在
    2. 如果存在且未过期，加载到 BrowserPool 的 context.add_cookies()
    3. 后续所有抓取都使用登录态

登录态检查与续期
---------------

def is_session_valid(session: dict) -> bool:
    expires_at = datetime.fromisoformat(session["expires_at"])
    return datetime.now() < expires_at

过期的会话：
  方案 A：用户重新跑 `python tools/login.py ctrip`（推荐）
  方案 B：检测到风控（登录态失效的标志：返回 302 到登录页）→ 自动提示续期

为什么用 BrowserPool 而非每个 Source 独立登录
-------------------------------------------

- 单个 Playwright 进程 = 1 个 Chrome = 所有平台共享同一浏览器实例
- 加载多个平台的 Cookie 到同一个 context 是可行的（不同域名 cookie 互不冲突）
- 节省 5x 启动时间，节省内存

风险与缓解
----------

| 风险 | 影响 | 缓解 |
|------|------|------|
| Cookie 泄露 | 他人可冒充用户 | 文件权限 600；不要 commit 到 git |
| 平台封号 | 频繁爬取触发风控 | 每平台加随机延迟；失败 3 次后停 1 小时 |
| 反爬升级 | Cookie+UA 仍被识别 | 配合 playwright-stealth 隐藏自动化痕迹 |
| 会话失效 | 抓取失败 | 检测到 302/401 → 自动重跑 login 流程 |

启动命令
--------

    # 单平台登录
    python tools/login.py ctrip

    # 一次性登录所有平台
    python tools/login.py all

    # 列出已登录的会话
    python tools/login.py list

    # 删除已过期的会话
    python tools/login.py clean
"""
