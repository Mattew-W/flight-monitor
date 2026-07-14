# ✈️ Flight Price Monitor — Multi-Platform Price Tracking & Forecasting

A Python-based flight price monitoring system with **data-driven price forecasting**, **multi-platform comparison** (28 purchase-platform entries), price trend analysis, and alert notifications. Comes with a web dashboard, an optional ML ensemble for richer forecasts, and opt-in real scrapers (Ctrip / Skyscanner / Amadeus) via Playwright.

## ✨ Features

- **Multi-Platform Comparison**: 28 purchase-platform entries — 4 domestic OTAs (Ctrip, Qunar, Fliggy, Tongcheng) + 6 domestic airline sites + 5 international OTAs (Trip.com, Skyscanner, Google Flights, Kayak, Expedia) + 13 international airline sites. Search returns a `platform_prices` array with **clickable purchase links**; platforms without a live quote show an estimated price (tagged `[预估]`).
- **Data-Driven Price Forecasting**: Route-profile-aware engine with 6 pricing profiles — `competitive`, `moderate`, `monopoly`, `budget`, `holiday`, `offpeak`. Uses a **Linear Regression + Weighted Moving Average (WMA) ensemble** with trend awareness, and backfills sparse history with profile-specific synthetic data.
- **Optional ML Ensemble**: When a route has **≥ 7 real price points**, an ensemble of Gradient Boosting / Random Forest / Ridge regressors (pure-Python implementation, no `sklearn` required) refines the forecast. Falls back to the statistical model otherwise.
- **Confidence & Recommendations**: 7–90 day forecast with a **95% confidence interval**, a `best_buy_window`, and a plain-language recommendation.
- **Real Browser Scraping (opt-in)**: Playwright-based fresh-browser-per-search mode for Ctrip, plus Skyscanner / Amadeus HTTP sources and multi-platform scrapers. Disabled by default — enable via `ENABLED_SOURCES`.
- **Price Alerts**: Set target prices and get notified via **Email / ServerChan (WeChat) / Feishu Webhook**.
- **Interactive Charts**: Chart.js trend visualization and a forecast chart with a **green star marker** at the predicted best-buy point.
- **One-Click Launcher**: `flight_monitor.bat` menu (start / stop / status / open browser / install deps / reset DB) for Windows.
- **CSV Export**: UTF-8 BOM export compatible with Excel.

## 🚀 Quick Start

### Requirements
- Python **3.11+**
- (Optional) Chrome browser — only for live scraping / real data sources

### Install
```bash
git clone https://github.com/Mattew-W/flight-monitor.git
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

# Or use the Windows launcher menu:
flight_monitor.bat
```

### Seed Data
```bash
python seed_data.py              # Mock data: 56 popular routes × 2 date windows
python seed_data.py --ctrip-only # Try live Ctrip scraping (requires Playwright + Chrome)
```

### One-Time Login (persist cookies, for live scraping)
```bash
python tools/login.py ctrip
```
> Login persistence (`ctrip_cookies.json` + `core/session_manager.py`) is only used when real scrapers are enabled. The default data source is **mock**, so it is not part of the default flow.

## 📊 Price Forecasting

```
Real price history (from DB)
    │
    ├─ Classify route → one of 6 profiles
    │   (competitive / moderate / monopoly / budget / holiday / offpeak)
    │
    ├─ < 5 points  → route-aware forecast (LR + WMA, synthetic history backfill)
    ├─ 5–6 points  → statistical ensemble (LR + WMA)  ← the "ARIMA" label is legacy
    └─ ≥ 7 points  → optional ML ensemble (GBR / RFR / Ridge, pure-Python)
    │
    └─ Output: 7–90 day forecast + 95% CI + best_buy_window + recommendation
```

- **Synthetic history** keeps forecasts sensible when a route has little real data: each profile has its own generator (`_SYNTHETIC_GENERATORS`).
- **Confidence bands** use a 1.96σ factor on the statistical path; the ML path bootstraps 100 resamples.

## 📁 Project Structure

```
flight_monitor/
├── main.py                 # Flask app entry (create_app → app.run on :5566)
├── seed_data.py            # Seed 56 routes × 2 windows of mock (+ optional Ctrip) data
├── config.py               # Cities, 56 routes, 28 purchase platforms, source toggles, notify config
├── requirements.txt        # flask, requests (+ optional curl_cffi / playwright / numpy)
├── flight_monitor.bat      # Windows launcher menu
│
├── api/routes.py           # Flask REST API (search / history / predict / alerts / compare / dashboard)
├── core/
│   ├── database.py         # SQLite (WAL + RLock thread-safe writes, transactional deletes)
│   ├── monitor.py          # Background monitoring engine (drives ENABLED_SOURCES, fires alerts)
│   ├── aggregator.py       # O(N) dedup + cross-platform price synthesis
│   ├── price_prediction.py # ★ Forecast engine: 6 profiles + synthetic history + LR/WMA + best_buy
│   ├── ml_predictor.py     # Optional GBR/RFR/Ridge ensemble (pure-Python)
│   ├── notifier.py         # Email / ServerChan / Feishu notifications
│   ├── models.py           # SearchQuery / FlightPrice / PriceAlert / AlertHistory dataclasses
│   ├── browser_pool.py     # Shared Playwright browser lifecycle
│   └── session_manager.py  # Login cookie persistence
│
├── datasources/
│   ├── mock_source.py          # Default: simulated multi-platform quotes
│   ├── ctrip_source.py         # Ctrip public low-price API (HTTP)
│   ├── ctrip_browser_source.py # Ctrip H5 browser scraper (Playwright)
│   ├── skyscanner_source.py    # Skyscanner browse quotes (HTTP, via skyscanner_client)
│   ├── skyscanner_client.py    # Skyscanner HTTP client
│   ├── amadeus_source.py       # Amadeus official REST API (free tier)
│   ├── multi_platform_scraper.py # Qunar / Fliggy / Tongcheng / AirChina (Playwright)
│   ├── multi_airline_scraper.py  # Multi-airline / OTA unified sniffer (Playwright)
│   ├── airline_sniffer.py      # Generic airline API sniffer (Playwright)
│   ├── ctrip_schedule_scraper.py # Route connectivity scraper (HTTP, standalone)
│   ├── schedule_from_prices.py # Rebuild schedules from DB prices (tooling)
│   ├── flight_schedules.py     # Built-in flight-number static timetable (backfill times)
│   └── base.py                 # DataSource abstract base class
│
├── static/   (CSS + vanilla-JS SPA)
├── templates/ (index.html)
└── tools/    (login / debug / inspection scripts)
```

## 🔌 Data Sources

| Source | Method | Default | Data |
|--------|--------|---------|------|
| Mock Engine | Deterministic seed | ✅ On | 4 domestic / 5 international OTA + airline-official quotes across 56 routes |
| Ctrip Browser | Playwright (fresh-per-search) | ❌ Opt-in | Real-time Ctrip flight prices |
| Ctrip API | `requests` HTTP | ❌ Opt-in | Ctrip public low-price API (rate-limited) |
| Skyscanner | HTTP (curl_cffi) | ❌ Opt-in | Browse quotes |
| Amadeus | REST (free 2k/mo) | ❌ Opt-in | Official flight offers |
| Multi-platform | Playwright | ❌ Opt-in | Qunar / Fliggy / Tongcheng / AirChina |

> **Note**: `ENABLED_SOURCES` in `config.py` controls which sources run. It defaults to `["mock"]`. Real scrapers must be enabled explicitly; not every key listed in the example comment is wired into the monitor (only `mock` / `ctrip` / `ctrip_browser` / `skyscanner` are registered).

## 🔧 Tech Stack

- **Backend**: Python 3.11+ + Flask
- **Database**: SQLite + WAL mode, thread-safe writes (`threading.RLock`), per-operation connections, transactional bulk deletes, 4 tables (`search_queries`, `price_records`, `price_alerts`, `alert_history`)
- **Forecasting**: Linear Regression + Weighted Moving Average ensemble; optional Gradient Boosting / Random Forest / Ridge (pure-Python, no sklearn dependency)
- **Browser**: Playwright (Chromium headless, fresh-per-search mode)
- **Frontend**: Chart.js + vanilla JavaScript SPA
- **Notifications**: SMTP Email, ServerChan (WeChat), Feishu Webhook

## ⚙️ Configuration

- **`ENABLED_SOURCES`** (`config.py`): which data sources are active. Default `["mock"]`.
- **Notifications** (environment variables):
  - Email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`
  - ServerChan (WeChat): `SERVERCHAN_KEY`
  - Feishu: `FEISHU_WEBHOOK`
- **Platforms**: `PURCHASE_PLATFORMS` in `config.py` defines 28 purchase-platform entries (name / color / icon / URL template).

## 📄 License

MIT
