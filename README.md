# ✈️ Flight Price Monitor — ML-Powered Multi-Platform Price Tracking

A Python-based flight price monitoring system with **machine learning price prediction** (Gradient Boosting), multi-platform comparison (27+ channels), price trend analysis, and alert notifications.

## ✨ Features

- **ML Price Prediction**: Gradient Boosting Regressor (GBR) with route-aware feature engineering — distance, competition, seasonality, volatility, holiday proximity, and trend features
- **Multi-Platform Comparison**: 27+ booking channels including Ctrip, Qunar, Fliggy, Tongcheng, major Chinese airlines, Trip.com, Skyscanner, Kayak, Expedia, and more
- **Data-Driven Forecasting**: Statistical ensemble (Linear Regression + Weighted Moving Average) as reliable fallback when training data is limited
- **Real Browser Scraping**: Playwright-based fresh-browser-per-search mode to bypass anti-crawl restrictions (Ctrip, Qunar, Fliggy, airline official sites)
- **Price Alerts**: Set target prices, get notified via Email / ServerChan (WeChat) / Feishu Webhook
- **Interactive Charts**: Chart.js-powered trend visualization with 95% confidence intervals
- **One-Click Login Persistence**: Cookie-based session management — log in once, crawl forever
- **Data Export**: CSV export with UTF-8 BOM for Excel

## 🚀 Quick Start

### Requirements
- Python 3.11+
- (Optional) Chrome browser — for real-time scraping

### Install
```bash
git clone https://github.com/your-username/flight-monitor.git
cd flight-monitor

python -m venv .venv
.venv\Scripts\activate    # Windows
source .venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
# Optional: playwright install chromium   # for live Ctrip scraping
```

### Launch
```bash
python main.py
# Open http://127.0.0.1:5566

# Or use the one-click launcher:
flight_monitor.bat
```

### Seed Data (populate routes + prices)
```bash
python seed_data.py              # Mock data (27 platforms, 55 routes)
python seed_data.py --ctrip-only # Try live Ctrip scraping
```

### One-Time Login (persist cookies)
```bash
python tools/login.py ctrip
```

## 🤖 ML Prediction Pipeline

```
Historical Prices
    │
    ├─ Feature Engineering
    │   ├─ Route distance (km)
    │   ├─ Competition level (1-6)
    │   ├─ Holiday proximity (days)
    │   ├─ Price volatility (σ/μ)
    │   ├─ 7-day & 30-day trends
    │   └─ Cabin class multiplier
    │
    ├─ Gradient Boosting Regressor (sklearn or pure-Python)
    │   ├─ 50 estimators, lr=0.1
    │   └─ Trained on rolling 1-day-ahead predictions
    │
    └─ Output: 7-90 day forecast + 95% CI
```

## 📁 Project Structure

```
flight_monitor/
├── main.py              # Web app entry point
├── seed_data.py          # Route & price data collection
├── config.py             # Cities, routes, platforms, sources
├── requirements.txt
├── flight_monitor.bat   # One-click launcher (Windows)
│
├── api/routes.py         # Flask REST API
├── core/
│   ├── database.py       # SQLite (WAL mode)
│   ├── monitor.py        # Background price monitor
│   ├── aggregator.py     # O(N) cross-platform price synthesis
│   ├── ml_predictor.py   # GBR ML model + feature engineering
│   ├── price_prediction.py # Ensemble: ML + LR + WMA
│   ├── browser_pool.py   # Shared Playwright instances
│   ├── session_manager.py # Login cookie persistence
│   ├── models.py, notifier.py
│
├── datasources/
│   ├── mock_source.py              # 27-platform simulated data
│   ├── ctrip_browser_source.py     # Ctrip H5 browser scraper
│   ├── skyscanner_source.py        # Skyscanner browse API
│   ├── amadeus_source.py           # Amadeus REST API (free tier)
│   ├── multi_platform_scraper.py   # Qunar/Fliggy/Tongcheng/AirChina
│   └── flight_schedules.py        # ~180 static schedule records
│
├── static/  (CSS + JS)
├── templates/ (HTML)
└── tools/   (login.py, debugging scripts)
```

## 📊 Data Sources

| Source | Method | Reliability | Data |
|--------|--------|------------|------|
| Mock Engine | Deterministic seed | ★★★★★ Always | 55 routes × 27 platforms |
| Ctrip Browser | Playwright fresh-browser | ★★ IP-dependent | Real-time flight prices |
| Skyscanner API | curl_cffi HTTP | ★★ Geo-blocked | Browse quotes |
| Amadeus API | REST (free 2k/mo) | ★★★★★ Official | Flight offers |

## 🔧 Tech Stack

- **Backend**: Python 3.13 + Flask
- **Database**: SQLite + WAL mode
- **ML**: GradientBoostingRegressor (sklearn) + pure-Python fallback
- **Stats**: Linear Regression, Weighted Moving Average, ARIMA-lite
- **Browser**: Playwright (Chromium headless, fresh-per-search mode)
- **Frontend**: Chart.js + vanilla JavaScript SPA
- **Notifications**: SMTP Email, ServerChan (WeChat), Feishu Webhook

## 📄 License

MIT
