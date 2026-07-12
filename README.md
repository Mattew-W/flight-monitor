# ✈️ 航班价格监控 (Flight Price Monitor)

基于 Python + Flask + Playwright 的多平台航班价格监控工具，支持携程等 20+ 平台比价、价格趋势预测和降价提醒。

## ✨ 功能特性

- **多平台比价**: 携程、去哪儿、飞猪、同程、国航、南航、东航、海航、春秋、吉祥等
- **携程真实数据**: 通过 Playwright headless 浏览器获取实时航班数据（非模拟）
- **智能预测**: ARIMA 模型 + 95% 置信区间，预测未来价格走势
- **降价提醒**: 设置目标价格，邮件/微信通知
- **数据导出**: CSV 格式导出所有价格记录

## 🚀 快速开始

### 环境要求
- Python 3.11+
- Chrome 浏览器

### 安装
```bash
# 克隆项目
git clone https://github.com/your-username/flight-monitor.git
cd flight-monitor

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux

# 安装依赖
pip install -r requirements.txt
playwright install chromium
```

### 启动
```bash
python main.py
# 打开浏览器访问 http://127.0.0.1:5566
```

或使用一键启动脚本（Windows）:
```
flight_monitor.bat
```

## 📁 项目结构

```
flight_monitor/
├── main.py                 # 入口文件
├── config.py               # 配置文件（城市、航线、平台信息）
├── requirements.txt        # Python 依赖
├── flight_monitor.bat      # 一键启动脚本
│
├── api/                    # Flask 路由
│   └── routes.py           # REST API
│
├── core/                   # 核心模块
│   ├── database.py         # SQLite 数据库
│   ├── monitor.py          # 价格监控引擎
│   ├── models.py           # 数据模型
│   ├── notifier.py         # 通知提醒
│   └── price_prediction.py # ARIMA 预测模型
│
├── datasources/            # 数据源
│   ├── mock_source.py      # 模拟数据
│   └── ctrip_browser_source.py  # 携程浏览器抓取
│
├── crawler/                # 爬虫工具
│   └── extract_real.py     # 真实数据提取
│
├── templates/              # HTML 模板
│   └── index.html
│
└── static/                 # 前端资源
    ├── css/style.css
    └── js/app.js
```

## 🔧 技术栈

- **后端**: Python 3.13 + Flask
- **数据库**: SQLite + WAL 模式
- **爬虫**: Playwright (headless Chrome)
- **预测**: numpy + ARIMA 模型
- **前端**: Chart.js + 原生 JavaScript

## 📊 数据源

| 来源 | 方式 | 数据量 |
|------|------|--------|
| 携程旅行网 | Playwright 浏览器拦截 | 真实航班数据 |
| 模拟数据 | 确定性种子生成 | 离线可用 |

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 License

MIT
