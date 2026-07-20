"""
Flight Monitor API — Dashboard / Monitor / Static Data Routes
"""
import io
import csv
import logging
from datetime import datetime
from flask import request, jsonify, render_template, Response
from api._shared import rate_limiter, check_api_key, client_ip, OPEN_MODE, CORS_ORIGIN
from config import CITY_CODES, PURCHASE_PLATFORMS, POPULAR_ROUTES, CITY_GROUPS

logger = logging.getLogger(__name__)


def register(app, db, monitor):
    """Register dashboard, monitor, export, and static-data routes."""

    # ── Index ─────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Static data ───────────────────────────────────────────

    @app.route("/api/cities")
    def get_cities():
        cities = [{"name": k, "code": v} for k, v in sorted(CITY_CODES.items())]
        return jsonify(cities)

    @app.route("/api/city-groups")
    def get_city_groups():
        return jsonify(CITY_GROUPS)

    @app.route("/api/platforms")
    def get_platforms():
        result = []
        for key, info in PURCHASE_PLATFORMS.items():
            result.append({
                "key": key,
                "name": info["name"],
                "color": info["color"],
                "icon": info["icon"],
            })
        return jsonify(result)

    @app.route("/api/popular-routes")
    def get_popular_routes():
        return jsonify(POPULAR_ROUTES)

    # ── Export ────────────────────────────────────────────────

    @app.route("/api/export", methods=["GET"])
    def export_data():
        query_id = request.args.get("query_id", type=int)
        records = db.get_all_prices_for_export(query_id)

        def _csv_safe(val):
            s = str(val) if val is not None else ""
            if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
                return "'" + s
            return s

        output = io.StringIO()
        output.write("\uFEFF")  # BOM for Excel CJK support
        writer = csv.writer(output)
        writer.writerow(["recorded_at", "departure", "destination", "flight_no",
                         "airline", "price", "source", "cabin_class"])
        for r in records:
            writer.writerow([
                _csv_safe(r.get("recorded_at", "")),
                _csv_safe(r.get("departure", "")),
                _csv_safe(r.get("destination", "")),
                _csv_safe(r.get("flight_no", "")),
                _csv_safe(r.get("airline", "")),
                round(r.get("price", 0), 0) if r.get("price") is not None else "",
                _csv_safe(r.get("source", "")),
                _csv_safe(r.get("cabin_class", "")),
            ])
        return Response(
            output.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=flight_prices.csv"},
        )

    # ── Dashboard ─────────────────────────────────────────────

    @app.route("/api/dashboard", methods=["GET"])
    def dashboard():
        all_queries = db.get_all_queries()
        user_queries = [q for q in all_queries
                        if not (q.label and ("(near)" in q.label or "(far)" in q.label))]
        user_query_ids = {q.id for q in user_queries}
        monitoring_count = sum(1 for q in user_queries if q.is_monitoring)
        alert_count = len(db.get_active_alerts())
        history = db.get_alert_history(5)
        all_prices = db.get_all_latest_prices()
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

    # ── Monitor control ───────────────────────────────────────

    @app.route("/api/monitor/status", methods=["GET"])
    def monitor_status():
        return jsonify({
            "running": monitor.is_running,
            "interval": monitor.interval,
            "sources": list(monitor.sources.keys()),
        })

    @app.route("/api/monitor/start", methods=["POST"])
    def start_monitor():
        auth_err = check_api_key()
        if auth_err:
            return auth_err
        if not rate_limiter.allow(client_ip(), max_calls=5, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429
        monitor.start()
        return jsonify({"message": "Monitor started", "running": True})

    @app.route("/api/monitor/stop", methods=["POST"])
    def stop_monitor():
        auth_err = check_api_key()
        if auth_err:
            return auth_err
        if not rate_limiter.allow(client_ip(), max_calls=5, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429
        monitor.stop()
        return jsonify({"message": "Monitor stopped", "running": False})
