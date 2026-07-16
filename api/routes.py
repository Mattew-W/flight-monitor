"""
Flight Monitor - Flask API Routes
RESTful API for the flight monitor frontend.
"""
import logging
import os
import csv
import io
import time
import threading
import hashlib
from collections import defaultdict, deque
from datetime import datetime
from flask import Flask, request, jsonify, render_template, Response
from core.database import Database
from core.models import SearchQuery, PriceAlert
from core.monitor import PriceMonitor
from core.price_prediction import generate_prediction_chart
from core.logging_config import setup_request_logging
from config import (
    DB_PATH, CITY_CODES,
    PURCHASE_PLATFORMS, POPULAR_ROUTES, CITY_GROUPS,
)

logger = logging.getLogger(__name__)

# ── Security / rate-limit config (env-driven, off by default for local use) ──
API_KEY = os.environ.get("FLIGHT_MONITOR_API_KEY", "")
CORS_ORIGIN = os.environ.get("FLIGHT_MONITOR_CORS_ORIGIN", "*")

# Valid cabin_class / trip_type values for input validation.
_VALID_CABIN = {"economy", "business", "first"}
_VALID_TRIP = {"oneway", "roundtrip"}


class _RateLimiter:
    """Simple in-memory per-IP token-bucket rate limiter.

    No external deps. Bounded memory (drops oldest entries when the IP table
    grows past _MAX_IPS). Single global instance shared across all endpoints.
    """
    _MAX_IPS = 4096

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, ip, max_calls, window_s):
        now = time.time()
        with self._lock:
            bucket = self._hits[ip]
            while bucket and now - bucket[0] > window_s:
                bucket.popleft()
            if len(bucket) >= max_calls:
                return False
            bucket.append(now)
            if len(self._hits) > self._MAX_IPS:
                cutoff = now - window_s
                self._hits = {k: v for k, v in self._hits.items()
                              if v and v[-1] > cutoff}
            return True


_rate_limiter = _RateLimiter()


def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")


def _check_api_key():
    """Return an error response if API key is required and missing/wrong.

    Returns None when the request is allowed to proceed.
    """
    if not API_KEY:
        return None  # No key configured → open mode (local dev).
    provided = request.headers.get("X-API-Key") or request.args.get("api_key", "")
    if provided == API_KEY:
        return None
    return jsonify({"error": "invalid or missing API key"}), 401


def _stable_seed(*parts):
    """Stable integer seed from string parts (md5, not Python's randomized hash)."""
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.md5(raw.encode("utf-8")).hexdigest()[:8], 16)


def create_app(db: Database = None, monitor: PriceMonitor = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
    )

    if db is None:
        db = Database(DB_PATH)
    if monitor is None:
        monitor = PriceMonitor(db)

    app.config["db"] = db
    app.config["monitor"] = monitor

    # ── S5: Structured request logging (request_id injection) ──
    setup_request_logging(app)

    # ── CORS + error handlers ───────────────────────────────────
    @app.after_request
    def _add_cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = CORS_ORIGIN
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return resp

    @app.errorhandler(404)
    def _not_found(e):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return jsonify({"error": "method not allowed"}), 405

    @app.errorhandler(500)
    def _internal_error(e):
        # Don't leak stack traces to clients.
        logger.exception("Unhandled 500 error")
        return jsonify({"error": "internal server error"}), 500

    # ── Pages ───────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── City codes ──────────────────────────────────────────────

    @app.route("/api/cities")
    def get_cities():
        cities = [{"name": k, "code": v} for k, v in sorted(CITY_CODES.items())]
        return jsonify(cities)

    @app.route("/api/city-groups")
    def get_city_groups():
        """Get cities grouped by region for the UI selector."""
        return jsonify(CITY_GROUPS)

    # ── Platforms / Purchase Channels ───────────────────────────

    @app.route("/api/platforms")
    def get_platforms():
        """Get all available booking platforms with their info."""
        result = []
        for key, info in PURCHASE_PLATFORMS.items():
            result.append({
                "key": key,
                "name": info["name"],
                "color": info["color"],
                "icon": info["icon"],
            })
        return jsonify(result)

    # ── Popular Routes ──────────────────────────────────────────

    @app.route("/api/popular-routes")
    def get_popular_routes():
        """Get popular route shortcuts."""
        return jsonify(POPULAR_ROUTES)

    # ── Search Queries ──────────────────────────────────────────

    @app.route("/api/queries", methods=["GET"])
    def list_queries():
        scope = request.args.get("scope", "all")  # all|user|seed
        # Clamp limit/offset to sane bounds to prevent memory blowups.
        limit = request.args.get("limit", type=int)
        if limit is not None:
            limit = max(1, min(limit, 1000))
        offset = max(0, request.args.get("offset", 0, type=int))
        all_queries = db.get_all_queries()

        # Backend filter: drop seed (label with (near)/(far)) when scope=user
        if scope == "user":
            queries = [q for q in all_queries
                       if not (q.label and ("(near)" in q.label or "(far)" in q.label))]
        elif scope == "seed":
            queries = [q for q in all_queries
                       if q.label and ("(near)" in q.label or "(far)" in q.label)]
        else:
            queries = all_queries

        if offset:
            queries = queries[offset:]
        if limit:
            queries = queries[:limit]

        result = []
        for q in queries:
            stats = db.get_price_stats(q.id)
            latest = db.get_latest_prices(q.id)
            min_price = min((p.price for p in latest), default=0)
            platforms = set()
            for p in latest:
                platforms.add(p.source)
            result.append({
                "id": q.id,
                "departure": q.departure,
                "destination": q.destination,
                "departure_date": q.departure_date,
                "cabin_class": q.cabin_class,
                "trip_type": q.trip_type,
                "return_date": q.return_date,
                "is_monitoring": q.is_monitoring,
                "created_at": q.created_at,
                "label": q.label,
                "stats": {
                    "min_price": round(stats["min_price"] or 0, 0),
                    "max_price": round(stats["max_price"] or 0, 0),
                    "avg_price": round(stats["avg_price"] or 0, 0),
                    "total_records": stats["total_records"],
                },
                "current_min_price": round(min_price, 0),
                "flight_count": len(latest),
                "platform_count": len(platforms),
            })
        return jsonify(result)

    @app.route("/api/queries", methods=["POST"])
    def create_query():
        data = request.get_json(silent=True) or {}

        # Validate required fields
        required = ["departure", "destination", "departure_date"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

        # Validate date format
        try:
            datetime.strptime(data["departure_date"], "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "departure_date must be YYYY-MM-DD"}), 400

        # Validate enum fields against whitelist
        cabin = data.get("cabin_class", "economy")
        if cabin not in _VALID_CABIN:
            return jsonify({"error": f"cabin_class must be one of {sorted(_VALID_CABIN)}"}), 400
        trip = data.get("trip_type", "oneway")
        if trip not in _VALID_TRIP:
            return jsonify({"error": f"trip_type must be one of {sorted(_VALID_TRIP)}"}), 400
        # roundtrip requires return_date
        if trip == "roundtrip" and not data.get("return_date"):
            return jsonify({"error": "return_date is required for roundtrip"}), 400

        q = SearchQuery(
            departure=data.get("departure", "").strip(),
            destination=data.get("destination", "").strip(),
            departure_date=data["departure_date"],
            cabin_class=cabin,
            trip_type=trip,
            return_date=data.get("return_date", ""),
            is_monitoring=data.get("is_monitoring", False),
            label=data.get("label", ""),
        )
        query_id = db.add_query(q)
        q.id = query_id
        return jsonify({"id": query_id, "message": "Query created"}), 201

    @app.route("/api/queries/<int:query_id>", methods=["DELETE"])
    def delete_query(query_id):
        # Check existence so caller gets a proper 404 (not silent 200).
        if not db.get_query(query_id):
            return jsonify({"error": "Query not found"}), 404
        db.delete_query(query_id)
        return jsonify({"message": "Deleted"})

    @app.route("/api/queries/bulk-delete", methods=["POST"])
    def bulk_delete_queries():
        data = request.get_json(silent=True) or {}
        ids = data.get("ids", [])
        if not isinstance(ids, list) or not ids:
            return jsonify({"error": "ids must be a non-empty list"}), 400
        if len(ids) > 200:
            return jsonify({"error": "bulk delete limited to 200 ids at a time"}), 400
        # Coerce ids to int safely; reject non-numeric entries instead of 500.
        clean_ids = []
        for i in ids:
            try:
                clean_ids.append(int(i))
            except (TypeError, ValueError):
                return jsonify({"error": f"invalid id: {i!r}"}), 400
        db.delete_queries_bulk(clean_ids)
        return jsonify({"message": "Deleted", "count": len(clean_ids)})

    @app.route("/api/queries/<int:query_id>/monitoring", methods=["PUT"])
    def toggle_monitoring(query_id):
        data = request.get_json(silent=True) or {}
        monitoring = bool(data.get("is_monitoring", False))
        if not db.get_query(query_id):
            return jsonify({"error": "Query not found"}), 404
        db.update_query_monitoring(query_id, monitoring)
        return jsonify({"message": "Updated", "is_monitoring": monitoring})

    @app.route("/api/queries/<int:query_id>/search", methods=["POST"])
    def search_now(query_id):
        """Trigger an immediate search for a query and store results."""
        # Auth first, then rate limit (avoid consuming quota for invalid keys).
        auth_err = _check_api_key()
        if auth_err:
            return auth_err
        # Rate limit: expensive crawler call — max 10/min per IP.
        if not _rate_limiter.allow(_client_ip(), max_calls=10, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429

        q = db.get_query(query_id)
        if not q:
            return jsonify({"error": "Query not found"}), 404

        try:
            # 1. Trigger crawler/monitor to get latest prices
            prices = monitor.check_query(q)

            # 2. Dispatch to Aggregator for O(N) high-speed processing
            from core.aggregator import FlightAggregator
            result = FlightAggregator.process_search_results(q, prices)
            return jsonify(result)
        except Exception as e:
            logger.exception(f"search_now failed for query {query_id}")
            return jsonify({"error": "search failed", "detail": str(e)[:200]}), 500

    @app.route("/api/queries/<int:query_id>/prices", methods=["GET"])
    def get_latest_prices(query_id):
        """Get latest prices for a query."""
        prices = db.get_latest_prices(query_id)
        return jsonify([
            {
                "airline": p.airline,
                "flight_no": p.flight_no,
                "aircraft": p.aircraft,
                "departure_time": p.departure_time,
                "arrival_time": p.arrival_time,
                "departure_airport": p.departure_airport,
                "arrival_airport": p.arrival_airport,
                "duration": p.duration,
                "stops": p.stops,
                "price": p.price,
                "source": p.source,
                "purchase_url": p.purchase_url,
                "recorded_at": p.recorded_at,
            }
            for p in prices
        ])

    @app.route("/api/queries/<int:query_id>/history", methods=["GET"])
    def get_price_history(query_id):
        """Get price history for charting."""
        limit = max(1, min(request.args.get("limit", 200, type=int) or 200, 1000))
        history = db.get_price_history(query_id, limit)
        history.reverse()
        return jsonify([
            {
                "recorded_at": h["date"],
                "min_price": round(h["min_price"], 0),
                "avg_price": round(h["avg_price"], 0),
                "max_price": round(h["max_price"], 0),
                "count": h["count"],
            }
            for h in history
        ])

    @app.route("/api/queries/<int:query_id>/predict", methods=["GET"])
    def predict_prices(query_id):
        """Generate price prediction chart for a query."""
        q = db.get_query(query_id)
        if not q:
            return jsonify({"error": "Query not found"}), 404
        try:
            result = generate_prediction_chart(
                db, query_id,
                q.departure, q.destination,
                q.departure_date, q.cabin_class,
            )
            return jsonify(result)
        except Exception as e:
            logger.exception(f"prediction failed for query {query_id}")
            return jsonify({"error": "prediction failed", "detail": str(e)[:200]}), 500

    @app.route("/api/queries/<int:query_id>/stats", methods=["GET"])
    def get_stats(query_id):
        stats = db.get_price_stats(query_id)
        return jsonify({
            "min_price": round(stats["min_price"] or 0, 0),
            "max_price": round(stats["max_price"] or 0, 0),
            "avg_price": round(stats["avg_price"] or 0, 0),
            "total_records": stats["total_records"],
        })

    # ── Export ──────────────────────────────────────────────────

    @app.route("/api/export", methods=["GET"])
    def export_data():
        """Export price records as CSV."""
        query_id = request.args.get("query_id", type=int)
        records = db.get_all_prices_for_export(query_id)

        output = io.StringIO()
        output.write('\ufeff')  # UTF-8 BOM for Excel compatibility
        writer = csv.writer(output)
        writer.writerow([
            "航线", "出发城市", "目的城市", "出发日期",
            "航空公司", "航班号", "机型", "出发时间", "到达时间",
            "出发机场", "到达机场", "航程", "经停", "价格",
            "舱位", "来源平台", "记录时间", "购买链接"
        ])
        for r in records:
            writer.writerow([
                f"{r.get('departure', '')} -> {r.get('destination', '')}",
                r.get("departure", ""),
                r.get("destination", ""),
                r.get("departure_date", ""),
                r.get("airline", ""),
                r.get("flight_no", ""),
                r.get("aircraft", ""),
                r.get("departure_time", ""),
                r.get("arrival_time", ""),
                r.get("departure_airport", ""),
                r.get("arrival_airport", ""),
                r.get("duration", ""),
                r.get("stops", 0),
                r.get("price", 0),
                r.get("cabin_class", ""),
                r.get("source", ""),
                r.get("recorded_at", ""),
                r.get("purchase_url", ""),
            ])

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=flight_prices.csv"}
        )

    # ── Alerts ──────────────────────────────────────────────────

    @app.route("/api/alerts", methods=["GET"])
    def list_alerts():
        query_id = request.args.get("query_id", type=int)
        alerts = db.get_alerts(query_id)
        result = []
        for a in alerts:
            q = db.get_query(a.query_id)
            result.append({
                "id": a.id,
                "query_id": a.query_id,
                "target_price": a.target_price,
                "is_active": a.is_active,
                "notify_email": a.notify_email,
                "notify_wechat": a.notify_wechat,
                "created_at": a.created_at,
                "last_triggered": a.last_triggered,
                "query_label": q.label if q else "",
                "query_route": f"{q.departure}→{q.destination}" if q else "",
                "query_date": q.departure_date if q else "",
            })
        return jsonify(result)

    @app.route("/api/alerts", methods=["POST"])
    def create_alert():
        data = request.get_json(silent=True) or {}

        if not data.get("query_id"):
            return jsonify({"error": "query_id is required"}), 400
        try:
            target_price = float(data.get("target_price", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "target_price must be a number"}), 400
        if target_price <= 0:
            return jsonify({"error": "target_price must be a positive number"}), 400

        # Verify query exists
        q = db.get_query(data["query_id"])
        if not q:
            return jsonify({"error": "Query not found"}), 404

        alert = PriceAlert(
            query_id=data["query_id"],
            target_price=target_price,
            is_active=data.get("is_active", True),
            notify_email=data.get("notify_email", True),
            notify_wechat=data.get("notify_wechat", False),
        )
        alert_id = db.add_alert(alert)
        return jsonify({"id": alert_id, "message": "Alert created"}), 201

    @app.route("/api/alerts/<int:alert_id>", methods=["PUT"])
    def update_alert(alert_id):
        data = request.get_json(silent=True) or {}
        target_price = data.get("target_price")
        if target_price is not None:
            try:
                target_price = float(target_price)
            except (TypeError, ValueError):
                return jsonify({"error": "target_price must be a number"}), 400
        db.update_alert(
            alert_id,
            target_price=target_price,
            is_active=data.get("is_active"),
        )
        return jsonify({"message": "Updated"})

    @app.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
    def delete_alert(alert_id):
        db.delete_alert(alert_id)
        return jsonify({"message": "Deleted"})

    @app.route("/api/alerts/history", methods=["GET"])
    def alert_history():
        history = db.get_alert_history(50)
        return jsonify(history)

    # ── Dashboard ───────────────────────────────────────────────

    @app.route("/api/dashboard", methods=["GET"])
    def dashboard():
        all_queries = db.get_all_queries()
        # Filter out seed data for the dashboard
        user_queries = [q for q in all_queries
                        if not (q.label and ("(near)" in q.label or "(far)" in q.label))]
        user_query_ids = {q.id for q in user_queries}
        monitoring_count = sum(1 for q in user_queries if q.is_monitoring)
        alert_count = len(db.get_active_alerts())
        history = db.get_alert_history(5)
        all_prices = db.get_all_latest_prices()
        # Drop prices belonging to seed queries
        all_prices = [p for p in all_prices if p.get("query_id") in user_query_ids]

        route_prices = {}
        for p in all_prices:
            key = p["query_id"]
            if key not in route_prices or p["price"] < route_prices[key]["price"]:
                route_prices[key] = p

        all_platforms = set(p.get("source", "") for p in all_prices if p.get("source"))

        return jsonify({
            "total_queries": len(user_queries),
            "monitoring_queries": monitoring_count,
            "active_alerts": alert_count,
            "recent_alerts": history,
            "route_prices": list(route_prices.values()),
            "platform_count": len(all_platforms),
        })

    # ── Monitor control ─────────────────────────────────────────

    @app.route("/api/monitor/status", methods=["GET"])
    def monitor_status():
        return jsonify({
            "running": monitor.is_running,
            "interval": monitor.interval,
            "sources": list(monitor.sources.keys()),
        })

    @app.route("/api/monitor/start", methods=["POST"])
    def start_monitor():
        auth_err = _check_api_key()
        if auth_err:
            return auth_err
        if not _rate_limiter.allow(_client_ip(), max_calls=5, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429
        monitor.start()
        return jsonify({"message": "Monitor started", "running": True})

    @app.route("/api/monitor/stop", methods=["POST"])
    def stop_monitor():
        auth_err = _check_api_key()
        if auth_err:
            return auth_err
        if not _rate_limiter.allow(_client_ip(), max_calls=5, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429
        monitor.stop()
        return jsonify({"message": "Monitor stopped", "running": False})

    # ── Flight schedule lookup ────────────────────────────────────
    @app.route("/api/flight/<flight_no>", methods=["GET"])
    def flight_lookup(flight_no):
        """Look up flight schedule by flight number."""
        try:
            from datasources.flight_schedules import lookup_flight_schedule
        except ImportError:
            return jsonify({"found": False, "error": "schedule db not available"}), 501
        sched = lookup_flight_schedule(flight_no)
        if sched:
            sched["found"] = True
            sched["flight_no"] = flight_no.upper()
            return jsonify(sched)
        return jsonify({"found": False, "flight_no": flight_no.upper()})

    @app.route("/api/flight/search", methods=["GET"])
    def flight_search():
        """Search flights by city pair (like Bing's flight info card)."""
        try:
            from datasources.flight_schedules import search_flights_by_route
        except ImportError:
            return jsonify({"error": "schedule db not available"}), 501
        dep = request.args.get("dep", "")
        arr = request.args.get("arr", "")
        if not dep or not arr:
            return jsonify({"error": "dep and arr are required"}), 400
        results = search_flights_by_route(dep, arr)
        return jsonify({"results": results, "count": len(results)})

    @app.route("/api/flight/live", methods=["GET"])
    def flight_live_price():
        """Fetch real-time price for a flight on a given date.

        Query params:
            dep, arr: city codes (e.g. SHA, CAN)
            date: YYYY-MM-DD
            cabin: economy / business / first (default economy)
        """
        # Rate limit: external Ctrip call — max 20/min per IP.
        if not _rate_limiter.allow(_client_ip(), max_calls=20, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429

        import requests as req
        dep = request.args.get("dep", "").upper()
        arr = request.args.get("arr", "").upper()
        date_str = request.args.get("date", "")
        cabin = request.args.get("cabin", "economy")

        if not dep or not arr or not date_str:
            return jsonify({"error": "missing params: dep, arr, date"}), 400
        # Validate date format to avoid confusing Ctrip API errors.
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400

        # Map cabin to Ctrip param
        cabin_map = {"economy": "Y_S", "business": "C_S", "first": "F_S"}
        cabin_param = cabin_map.get(cabin, "Y_S")

        # Use the existing Ctrip lowest-price calendar API
        # This is the public API used by m.ctrip.com
        url = "https://m.ctrip.com/restapi/soa2/14666/json/getLowestPriceCalendar"
        try:
            resp = req.get(
                url,
                params={
                    "DepartCityCode": dep,
                    "ArriveCityCode": arr,
                    "StartDate": date_str,
                    "EndDate": date_str,
                    "cabin": cabin_param,
                    "adult": 1,
                    "child": 0,
                    "infant": 0,
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
                    "Accept": "application/json",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Try to extract price from various response shapes
                price = None
                items = data.get("LowestPriceCalendarItems") or data.get("Items") or data.get("data") or []
                if items and len(items) > 0:
                    for item in items:
                        if item.get("Date") == date_str or item.get("DepartDate") == date_str:
                            price = item.get("LowestPrice") or item.get("Price") or item.get("price")
                            break
                    if price is None and items[0]:
                        price = items[0].get("LowestPrice") or items[0].get("Price") or items[0].get("price")
                if price:
                    return jsonify({
                        "found": True,
                        "dep": dep, "arr": arr, "date": date_str, "cabin": cabin,
                        "price": float(price),
                        "source": "ctrip_calendar",
                    })
            return jsonify({
                "found": False,
                "dep": dep, "arr": arr, "date": date_str,
                "error": f"HTTP {resp.status_code}",
            })
        except Exception as e:
            # Don't leak full exception (may contain internal URLs / paths).
            logger.warning(f"flight_live_price failed: {type(e).__name__}")
            return jsonify({"found": False, "error": "external API call failed"}), 502

    # ── Bing Search for flight prices ─────────────────────────────
    @app.route("/api/flight/bing", methods=["GET"])
    def flight_bing_search():
        """Search Bing for real-time flight prices.

        Query params:
            dep: departure city name (e.g. 北京)
            arr: arrival city name (e.g. 上海)
            date: YYYY-MM-DD
            cabin: economy / business / first (default economy)
        """
        # Rate limit: external search — max 10/min per IP.
        if not _rate_limiter.allow(_client_ip(), max_calls=10, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429

        dep = request.args.get("dep", "").strip()
        arr = request.args.get("arr", "").strip()
        date_str = request.args.get("date", "")
        cabin = request.args.get("cabin", "economy")

        if not dep or not arr or not date_str:
            return jsonify({"error": "missing params: dep, arr, date"}), 400

        try:
            from datasources.bing_search_source import BingSearchSource
            from core.models import SearchQuery

            bing = BingSearchSource()
            if not bing.is_available():
                return jsonify({"error": "bing search not available (requests lib missing)"}), 501

            # Build a temporary SearchQuery for the Bing source
            q = SearchQuery(
                departure=dep,
                destination=arr,
                departure_date=date_str,
                cabin_class=cabin,
            )
            flights = bing.search_flights(q)

            if flights:
                return jsonify({
                    "found": True,
                    "dep": dep, "arr": arr, "date": date_str, "cabin": cabin,
                    "count": len(flights),
                    "min_price": min(f.price for f in flights),
                    "max_price": max(f.price for f in flights),
                    "flights": [
                        {
                            "airline": f.airline,
                            "flight_no": f.flight_no,
                            "price": f.price,
                            "departure_airport": f.departure_airport,
                            "arrival_airport": f.arrival_airport,
                            "purchase_url": f.purchase_url,
                        }
                        for f in flights[:20]
                    ],
                    "source": "bing",
                })
            return jsonify({
                "found": False,
                "dep": dep, "arr": arr, "date": date_str,
                "error": "no prices found in Bing results",
            })
        except Exception as e:
            logger.warning(f"flight_bing_search failed: {type(e).__name__}")
            return jsonify({"found": False, "error": "bing search failed"}), 502

    @app.route("/api/flight/bing_route", methods=["GET"])
    def flight_bing_route_lookup():
        """Search Bing for flight route info (departure/arrival cities) by flight number.

        Query params:
            flight_no: flight number like 'ZH9103'
        """
        flight_no = request.args.get("flight_no", "").strip()
        if not flight_no:
            return jsonify({"found": False, "error": "missing flight_no"}), 400

        if not _rate_limiter.allow(_client_ip(), max_calls=10, window_s=60):
            return jsonify({"error": "rate limit exceeded"}), 429

        try:
            from datasources.bing_search_source import BingSearchSource
            bing = BingSearchSource()
            if not bing.is_available():
                return jsonify({"found": False, "error": "bing not available"}), 503

            route_info = bing.lookup_flight_route(flight_no)
            if route_info:
                route_info["found"] = True
                route_info["flight_no"] = flight_no.upper()
                return jsonify(route_info)
            return jsonify({"found": False, "flight_no": flight_no.upper()})
        except Exception as e:
            logger.warning(f"flight_bing_route failed: {type(e).__name__}: {e}")
            return jsonify({"found": False, "error": "route lookup failed"}), 502

    # ── Manual prediction from user-entered price ─────────────────
    @app.route("/api/predict/manual", methods=["POST"])
    def manual_predict():
        """Predict price curve from a single user-entered price point.
        
        Request JSON:
            { "departure": "北京", "destination": "上海",
              "departure_date": "2026-08-15",
              "price": 450,                # current price you see
              "cabin_class": "economy" }
        
        Uses the 88-day real BJS->SHA pattern scaled to the route's base price
        and anchored at the user's current price.
        """
        import math, random
        from core.price_prediction import _classify_route, _PROFILE_LABELS, arima_forecast

        data = request.get_json(silent=True) or {}
        dep = data.get("departure", "")
        dst = data.get("destination", "")
        dep_date_str = data.get("departure_date", "")
        price = float(data.get("price", 0))
        cabin = data.get("cabin_class", "economy")

        if not dep or not dst or not dep_date_str or price <= 0:
            return jsonify({"error": "请填写出发地、目的地、日期和当前价格"}), 400

        try:
            dep_date = datetime.strptime(dep_date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "日期格式错误，请用 YYYY-MM-DD"}), 400

        days_until = max(1, (dep_date - datetime.now()).days)

        # Generate 30 days of synthetic history based on real pattern ratios
        from core.price_prediction import HolidayManager
        route_info = _classify_route(dep, dst, dep_date)
        profile = route_info["profile"]

        # Build fake history: 30 days, prices fluctuate around user's price
        rng = random.Random(_stable_seed(dep, dst, dep_date_str) % 2**31)
        base = price

        # Get real price ratios from BJS->SHA pattern (stored in DB)
        # Use the public accessor instead of reaching into db._get_conn().
        ratios = None
        try:
            rows = db.get_daily_min_prices(query_id=1595, real_only=True)
            if len(rows) >= 7:
                real_prices = [r["min_price"] for r in rows]
                real_base = max(real_prices[0], 1)
                ratios = [p / real_base for p in real_prices]
        except Exception:
            logger.debug("manual_predict: real ratio lookup failed", exc_info=True)

        # Build history: last 30 ratios anchored to user's price
        if ratios and len(ratios) >= 7:
            use_ratios = ratios[-30:] if len(ratios) >= 30 else ratios
            # Add route-specific noise so different routes don't share the
            # exact same pattern and best-buy date (jittered by ~5% per point)
            route_seed = _stable_seed(dep, dst, cabin) % 1000
            route_rng = random.Random(route_seed)
            hist_prices = []
            for r in use_ratios:
                jitter = 1.0 + route_rng.uniform(-0.05, 0.05)
                hist_prices.append(round(price * r * jitter / 10) * 10)
        else:
            # Fallback: random walk around user's price
            hist_prices = [price]
            for _ in range(29):
                price = price * (1.0 + rng.uniform(-0.03, 0.03))
                price = max(price * 0.7, min(price * 1.3, price))
                hist_prices.append(round(price / 10) * 10)

        # Generate forecast using the data-driven model
        from core.price_prediction import arima_forecast, data_driven_forecast
        if len(hist_prices) >= 7:
            result = data_driven_forecast(hist_prices, days_until, profile)
        else:
            result = arima_forecast(hist_prices, days_until)

        # Build chart data
        from datetime import timedelta
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        hist_dates = [(today - timedelta(days=len(hist_prices) - i)).strftime("%Y-%m-%d") for i in range(len(hist_prices))]
        future_dates = [(today + timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(days_until)]

        forecast = result.get("forecast", [])
        lower = result.get("lower", [])
        upper = result.get("upper", [])

        # Best-buy logic
        current = hist_prices[-1] if hist_prices else price
        pred_min = min(forecast) if forecast else current
        pred_max = max(forecast) if forecast else current
        min_idx = forecast.index(pred_min) if forecast and pred_min in forecast else 0
        min_date = future_dates[min_idx] if min_idx < len(future_dates) else ""

        drop_pct = (current - pred_min) / current * 100
        rise_pct = (pred_max - current) / current * 100

        buy = ""
        if days_until <= 3:
            buy = "距起飞仅%d天，建议立即购买" % days_until
        elif profile == "holiday":
            buy = "节假日前%.0f%%涨幅预期，建议尽快锁定价格" % rise_pct
        elif drop_pct >= 10 and days_until >= 14:
            buy = "预计降至%.0f（降%.0f%%），最佳入手: %s" % (pred_min, drop_pct, min_date)
        elif drop_pct >= 5 and days_until >= 7:
            buy = "预计小幅下降至%.0f，可观望至%s" % (pred_min, min_date)
        elif rise_pct >= 5:
            buy = "价格预计上涨%.0f%%，建议%d天内锁定" % (rise_pct, days_until // 2)
        elif rise_pct >= 3:
            buy = "价格预计上涨%.0f%%，建议尽早入手" % rise_pct
        elif drop_pct > 0:
            buy = "价格稳定，可观望至%s" % min_date

        return jsonify({
            "departure": dep,
            "destination": dst,
            "departure_date": dep_date_str,
            "current_price": round(current),
            "days_until_departure": days_until,
            "route_profile": profile,
            "route_profile_label": _PROFILE_LABELS.get(profile, ""),
            "model": result.get("model", "手动预测"),
            "forecast": forecast,
            "lower": lower,
            "upper": upper,
            "historical_min": min(hist_prices),
            "predicted_min": round(pred_min),
            "predicted_min_date": min_date,
            "best_buy_window": buy,
            "chart": {
                "labels": hist_dates + future_dates,
                "historical_prices": hist_prices + [None] * days_until,
                "forecast_prices": [None] * (len(hist_prices) - 1) + [current] + forecast,
                "lower_bound": [None] * (len(hist_prices) - 1) + [current] + lower,
                "upper_bound": [None] * (len(hist_prices) - 1) + [current] + upper,
            },
        })

    return app
