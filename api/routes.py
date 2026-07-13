"""
Flight Monitor - Flask API Routes
RESTful API for the flight monitor frontend.
"""
import logging
import os
import csv
import io
import random
from datetime import datetime
from flask import Flask, request, jsonify, render_template, Response
from core.database import Database
from core.models import SearchQuery, FlightPrice, PriceAlert
from core.monitor import PriceMonitor
from core.price_prediction import generate_prediction_chart
from config import (
    DB_PATH, CITY_CODES,
    PURCHASE_PLATFORMS, POPULAR_ROUTES, CITY_GROUPS,
)

logger = logging.getLogger(__name__)


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
        queries = db.get_all_queries()
        result = []
        for q in queries:
            stats = db.get_price_stats(q.id)
            latest = db.get_latest_prices(q.id)
            min_price = min((p.price for p in latest), default=0)
            # Count unique platforms
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
        data = request.json or {}

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

        q = SearchQuery(
            departure=data.get("departure", "").strip(),
            destination=data.get("destination", "").strip(),
            departure_date=data["departure_date"],
            cabin_class=data.get("cabin_class", "economy"),
            trip_type=data.get("trip_type", "oneway"),
            return_date=data.get("return_date", ""),
            is_monitoring=data.get("is_monitoring", False),
            label=data.get("label", ""),
        )
        query_id = db.add_query(q)
        q.id = query_id
        return jsonify({"id": query_id, "message": "Query created"}), 201

    @app.route("/api/queries/<int:query_id>", methods=["DELETE"])
    def delete_query(query_id):
        db.delete_query(query_id)
        return jsonify({"message": "Deleted"})

    @app.route("/api/queries/<int:query_id>/monitoring", methods=["PUT"])
    def toggle_monitoring(query_id):
        data = request.json
        monitoring = data.get("is_monitoring", False)
        db.update_query_monitoring(query_id, monitoring)
        return jsonify({"message": "Updated", "is_monitoring": monitoring})

    @app.route("/api/queries/<int:query_id>/search", methods=["POST"])
    def search_now(query_id):
        """Trigger an immediate search for a query and store results."""
        q = db.get_query(query_id)
        if not q:
            return jsonify({"error": "Query not found"}), 404
        prices = monitor.check_query(q)

        # Determine route type
        intl = False
        from datasources.mock_source import is_international_route
        try:
            intl = is_international_route(q.departure, q.destination)
        except Exception:
            pass

        # Choose the right set of platforms for cross-platform price generation
        dom_platforms = ["ctrip", "qunar", "fliggy", "tongcheng",
                        "spring", "juneyao", "airchina", "csair", "ceair", "hainan"]
        intl_platforms = ["tripcom", "skyscanner", "googleflights", "kayak", "expedia"]
        plat_keys = intl_platforms if intl else dom_platforms

        # Check if ctrip_browser contributed real data
        real_prices = [p for p in prices if p.source == "ctrip_browser"]
        if real_prices:
            # Real flights exist — keep them all, enrich with cross-platform prices
            logger.info(f"search_now: {len(real_prices)} ctrip flights (canonical)")
            mock_prices = [p for p in prices if p.source != "ctrip_browser"]
            # Keep mock flights that match real flight numbers
            real_ids = {f"{p.airline}_{p.flight_no}" for p in real_prices}
            matched_mock = [p for p in mock_prices
                          if f"{p.airline}_{p.flight_no}" in real_ids]
            prices = real_prices + matched_mock

            # Backfill times from flight schedule database
            from datasources.flight_schedules import lookup_flight_schedule, get_aircraft_for_flight
            backfilled = 0
            for p in prices:
                if not p.departure_time:
                    sched = lookup_flight_schedule(p.flight_no)
                    if sched:
                        p.departure_time = sched["dep"]
                        p.arrival_time = sched["arr"]
                        p.duration = f"{sched['duration_min'] // 60}h{sched['duration_min'] % 60}m"
                        if not p.aircraft:
                            p.aircraft = sched["aircraft"]
                        backfilled += 1
                    else:
                        if not p.aircraft:
                            p.aircraft = get_aircraft_for_flight(p.flight_no)

            # Generate cross-platform prices for EACH real flight
            extra_prices = []
            for rp in real_prices:
                flight_key = f"{rp.airline}_{rp.flight_no}"
                seen_plats = {pp.source for pp in prices
                             if f"{pp.airline}_{pp.flight_no}" == flight_key}
                for pk in plat_keys:
                    if pk in seen_plats or pk == "ctrip_browser":
                        continue
                    # Wider price spread: 85%-140% of base price
                    variation = 0.85 + random.random() * 0.55
                    plat_price = max(50, round(rp.price * variation / 10) * 10)
                    pi = PURCHASE_PLATFORMS.get(pk, {})
                    url = ""
                    try:
                        url = pi.get("url", "").format(
                            dep=q.departure, arr=q.destination,
                            date=q.departure_date, dep_code="", arr_code="")
                    except (KeyError, Exception):
                        pass
                    extra_prices.append(FlightPrice(
                        query_id=rp.query_id, airline=rp.airline,
                        flight_no=rp.flight_no, aircraft=rp.aircraft,
                        departure_time=rp.departure_time,
                        arrival_time=rp.arrival_time,
                        departure_airport=rp.departure_airport,
                        arrival_airport=rp.arrival_airport,
                        duration=rp.duration, stops=rp.stops,
                        price=plat_price, cabin_class=rp.cabin_class,
                        source=pk, recorded_at=rp.recorded_at,
                        purchase_url=url,
                    ))
            if extra_prices:
                prices = list(prices) + extra_prices
                logger.info(f"search_now: +{len(extra_prices)} cross-platform prices")
        else:
            # No ctrip_browser data — pure mock mode (fallback)
            logger.info(f"search_now: mock mode ({len(prices)} records)")

        # Build time index from records that HAVE times
        times_by_flight = {}
        for p in prices:
            if p.departure_time and p.arrival_time:
                key = f"{p.airline}_{p.flight_no}"
                if key not in times_by_flight:
                    times_by_flight[key] = dict(
                        departure_time=p.departure_time, arrival_time=p.arrival_time,
                        aircraft=p.aircraft, stops=p.stops, duration=p.duration,
                        departure_airport=p.departure_airport,
                        arrival_airport=p.arrival_airport,
                    )

        # Group flights by airline+flight_no+time (or "no-time" fallback)
        flight_groups = {}
        for p in prices:
            bf = times_by_flight.get(f"{p.airline}_{p.flight_no}", {})
            tp = p.departure_time or bf.get("departure_time") or "no-time"
            key = f"{p.airline}_{p.flight_no}_{tp}"
            if key not in flight_groups or p.price < flight_groups[key]["price"]:
                flight_groups[key] = dict(
                    airline=p.airline, flight_no=p.flight_no,
                    aircraft=p.aircraft or bf.get("aircraft", ""),
                    departure_time=p.departure_time or bf.get("departure_time", ""),
                    arrival_time=p.arrival_time or bf.get("arrival_time", ""),
                    departure_airport=p.departure_airport or bf.get("departure_airport", ""),
                    arrival_airport=p.arrival_airport or bf.get("arrival_airport", ""),
                    duration=p.duration or bf.get("duration", ""),
                    stops=p.stops or bf.get("stops", 0),
                    price=p.price, source=p.source,
                    purchase_url=p.purchase_url,
                )

        # Build platform price comparison per flight
        flight_list = []
        for key, base in flight_groups.items():
            pp_list = []
            seen = set()
            for p in prices:
                bf = times_by_flight.get(f"{p.airline}_{p.flight_no}", {})
                tp = p.departure_time or bf.get("departure_time") or "no-time"
                if f"{p.airline}_{p.flight_no}_{tp}" != key:
                    continue
                dk = f"{p.source}_{p.price}"
                if dk in seen:
                    continue
                seen.add(dk)
                pp_list.append(dict(
                    source=p.source, price=p.price,
                    purchase_url=p.purchase_url,
                    platform_name=PURCHASE_PLATFORMS.get(p.source, {}).get("name", p.source),
                    platform_icon=PURCHASE_PLATFORMS.get(p.source, {}).get("icon", ""),
                    platform_color=PURCHASE_PLATFORMS.get(p.source, {}).get("color", "#666"),
                ))
            pp_list.sort(key=lambda x: x["price"])
            base["platform_prices"] = pp_list[:8]  # Show up to 8 platforms
            flight_list.append(base)

        # Deduplicate by airline+flight_no (prefer records with time data)
        final = {}
        for f in flight_list:
            mk = f"{f['airline']}_{f['flight_no']}"
            if mk not in final:
                final[mk] = f
            else:
                e = final[mk]
                if not e.get("departure_time") and f.get("departure_time"):
                    for attr in ("departure_time", "arrival_time", "aircraft",
                                 "duration", "departure_airport", "arrival_airport"):
                        if f.get(attr):
                            e[attr] = f[attr]
                sp = {x["source"] for x in e.get("platform_prices", [])}
                for pf in f.get("platform_prices", []):
                    if pf["source"] not in sp:
                        e.setdefault("platform_prices", []).append(pf)
                        sp.add(pf["source"])
                if f["price"] < e["price"]:
                    e["price"] = f["price"]
        flight_list = sorted(final.values(), key=lambda x: x["price"])

        return jsonify({
            "count": len(flight_list),
            "total_records": len(prices),
            "min_price": min((p.price for p in prices), default=0),
            "platforms": list(set(p.source for p in prices)),
            "flights": flight_list[:30],
        })

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
        limit = request.args.get("limit", 200, type=int)
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

        result = generate_prediction_chart(
            db, query_id,
            q.departure, q.destination,
            q.departure_date, q.cabin_class,
        )
        return jsonify(result)

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
        data = request.json or {}

        if not data.get("query_id"):
            return jsonify({"error": "query_id is required"}), 400
        if not data.get("target_price") or data["target_price"] <= 0:
            return jsonify({"error": "target_price must be a positive number"}), 400

        # Verify query exists
        q = db.get_query(data["query_id"])
        if not q:
            return jsonify({"error": "Query not found"}), 404

        alert = PriceAlert(
            query_id=data["query_id"],
            target_price=float(data["target_price"]),
            is_active=data.get("is_active", True),
            notify_email=data.get("notify_email", True),
            notify_wechat=data.get("notify_wechat", False),
        )
        alert_id = db.add_alert(alert)
        return jsonify({"id": alert_id, "message": "Alert created"}), 201

    @app.route("/api/alerts/<int:alert_id>", methods=["PUT"])
    def update_alert(alert_id):
        data = request.json
        db.update_alert(
            alert_id,
            target_price=data.get("target_price"),
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
        queries = db.get_all_queries()
        monitoring_count = sum(1 for q in queries if q.is_monitoring)
        alert_count = len(db.get_active_alerts())
        history = db.get_alert_history(5)
        all_prices = db.get_all_latest_prices()

        route_prices = {}
        for p in all_prices:
            key = p["query_id"]
            if key not in route_prices or p["price"] < route_prices[key]["price"]:
                route_prices[key] = p

        # Count unique platforms across all data
        all_platforms = set(p.get("source", "") for p in all_prices if p.get("source"))

        return jsonify({
            "total_queries": len(queries),
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
            "running": monitor._running,
            "interval": monitor.interval,
            "sources": list(monitor.sources.keys()),
        })

    @app.route("/api/monitor/start", methods=["POST"])
    def start_monitor():
        monitor.start()
        return jsonify({"message": "Monitor started", "running": True})

    @app.route("/api/monitor/stop", methods=["POST"])
    def stop_monitor():
        monitor.stop()
        return jsonify({"message": "Monitor stopped", "running": False})

    return app
