"""
Flight Monitor API — Query / Predict / Model Routes
"""
import logging
from datetime import datetime
from flask import request, jsonify
from core.models import SearchQuery
from api._shared import rate_limiter, check_api_key, client_ip, stable_seed, _VALID_CABIN

_VALID_TRIP = {"oneway", "roundtrip"}

logger = logging.getLogger(__name__)


def register(app, db, monitor):
    """Register all query, predict, and model-related routes."""

    # ── Queries CRUD ──────────────────────────────────────────

    @app.route("/api/queries", methods=["GET"])
    def list_queries():
        scope = request.args.get("scope", "all")
        limit = request.args.get("limit", type=int)
        if limit is not None:
            limit = max(1, min(limit, 1000))
        offset = max(0, request.args.get("offset", 0, type=int) or 0)
        all_queries = db.get_all_queries()

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
        required = ["departure", "destination", "departure_date"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
        try:
            datetime.strptime(data["departure_date"], "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "departure_date must be YYYY-MM-DD"}), 400
        cabin = data.get("cabin_class", "economy")
        if cabin not in _VALID_CABIN:
            return jsonify({"error": f"cabin_class must be one of {sorted(_VALID_CABIN)}"}), 400
        trip = data.get("trip_type", "oneway")
        if trip not in _VALID_TRIP:
            return jsonify({"error": f"trip_type must be one of {sorted(_VALID_TRIP)}"}), 400
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

    # ── Search ────────────────────────────────────────────────

    @app.route("/api/queries/<int:query_id>/search", methods=["POST"])
    def search_now(query_id):
        auth_err = check_api_key()
        if auth_err:
            return auth_err
        if not rate_limiter.allow(client_ip(), max_calls=10, window_s=60):
            return jsonify({"error": "rate limit exceeded, try again later"}), 429
        q = db.get_query(query_id)
        if not q:
            return jsonify({"error": "Query not found"}), 404
        try:
            prices = monitor.search_once(q)
            try:
                db.add_price_records(prices)
            except Exception:
                logger.warning(
                    f"search_now: failed to persist prices for query {query_id}",
                    exc_info=True,
                )
            from core.aggregator import FlightAggregator
            result = FlightAggregator.process_search_results(q, prices)
            return jsonify(result)
        except Exception as e:
            logger.exception(f"search_now failed for query {query_id}")
            return jsonify({"error": "search failed", "detail": str(e)[:200]}), 500

    # ── Prices & History ──────────────────────────────────────

    @app.route("/api/queries/<int:query_id>/prices", methods=["GET"])
    def get_latest_prices(query_id):
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

    @app.route("/api/queries/<int:query_id>/stats", methods=["GET"])
    def get_stats(query_id):
        stats = db.get_price_stats(query_id)
        return jsonify({
            "min_price": round(stats["min_price"] or 0, 0),
            "max_price": round(stats["max_price"] or 0, 0),
            "avg_price": round(stats["avg_price"] or 0, 0),
            "total_records": stats["total_records"],
        })

    # ── Prediction ────────────────────────────────────────────

    @app.route("/api/queries/<int:query_id>/predict", methods=["GET"])
    def predict_prices(query_id):
        from core.price_prediction import generate_prediction_chart
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

    @app.route("/api/predict/manual", methods=["POST"])
    def manual_predict():
        import math, random
        from core.price_prediction import _classify_route, _PROFILE_LABELS, arima_forecast

        data = request.get_json(silent=True) or {}
        dep = data.get("departure", "")
        dst = data.get("destination", "")
        dep_date_str = data.get("departure_date", "")
        try:
            price = float(data.get("price", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "价格必须是有效数字"}), 400
        if not math.isfinite(price) or price <= 0:
            return jsonify({"error": "价格必须是一个有效的正数"}), 400
        cabin = data.get("cabin_class", "economy")
        if not dep or not dst or not dep_date_str:
            return jsonify({"error": "请填写出发地、目的地、日期和当前价格"}), 400
        try:
            dep_date = datetime.strptime(dep_date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "日期格式错误，请用 YYYY-MM-DD"}), 400

        days_until = max(1, (dep_date - datetime.now()).days)
        from core.price_prediction import HolidayManager
        route_info = _classify_route(dep, dst, dep_date)
        profile = route_info["profile"]

        rng = random.Random(stable_seed(dep, dst, dep_date_str) % 2**31)
        base = price

        ratios = None
        try:
            rows = db.get_daily_min_prices(query_id=1595, real_only=True)
            if len(rows) >= 7:
                real_prices = [r["min_price"] for r in rows]
                real_base = max(real_prices[0], 1)
                ratios = [p / real_base for p in real_prices]
        except Exception:
            logger.debug("manual_predict: real ratio lookup failed", exc_info=True)

        if ratios and len(ratios) >= 7:
            use_ratios = ratios[-30:] if len(ratios) >= 30 else ratios
            route_seed = stable_seed(dep, dst, cabin) % 1000
            route_rng = random.Random(route_seed)
            hist_prices = []
            for r in use_ratios:
                jitter = 1.0 + route_rng.uniform(-0.05, 0.05)
                hist_prices.append(round(price * r * jitter / 10) * 10)
        else:
            hist_prices = [price]
            for _ in range(29):
                price = price * (1.0 + rng.uniform(-0.03, 0.03))
                price = max(price * 0.7, min(price * 1.3, price))
                hist_prices.append(round(price / 10) * 10)

        from core.price_prediction import arima_forecast, data_driven_forecast
        if len(hist_prices) >= 7:
            result = data_driven_forecast(hist_prices, days_until, profile)
        else:
            result = arima_forecast(hist_prices, days_until)

        from datetime import timedelta
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        hist_dates = [(today - timedelta(days=len(hist_prices) - i)).strftime("%Y-%m-%d") for i in range(len(hist_prices))]
        future_dates = [(today + timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(days_until)]

        forecast = result.get("forecast", [])
        lower = result.get("lower", [])
        upper = result.get("upper", [])

        current = hist_prices[-1] if hist_prices else price
        pred_min = min(forecast) if forecast else current
        pred_max = max(forecast) if forecast else current
        min_idx = forecast.index(pred_min) if forecast and pred_min in forecast else 0

        return jsonify({
            "hist_dates": hist_dates,
            "hist_prices": hist_prices,
            "future_dates": future_dates,
            "forecast": forecast,
            "lower_bound": lower,
            "upper_bound": upper,
            "current_price": current,
            "pred_min": pred_min,
            "pred_max": pred_max,
            "best_buy_date": future_dates[min_idx] if min_idx < len(future_dates) else None,
            "trend": "涨" if forecast and forecast[-1] > current else "跌" if forecast and forecast[-1] < current else "不变",
            "profile": _PROFILE_LABELS.get(profile, profile),
            "method": result.get("method", "arima"),
        })

    # ── Model Management (M4) ─────────────────────────────────

    @app.route("/api/queries/<int:query_id>/model_info", methods=["GET"])
    def model_info(query_id):
        if not db.get_query(query_id):
            return jsonify({"error": "Query not found"}), 404
        store = monitor.model_store
        versions = store.list_versions(query_id)
        latest = versions[-1] if versions else None
        best_ver = store.get_best_version(query_id, metric="r2")
        return jsonify({
            "query_id": query_id,
            "total_versions": len(versions),
            "latest_version": latest["version"] if latest else None,
            "latest_metrics": latest.get("metrics", {}) if latest else {},
            "best_r2_version": best_ver,
            "has_model": latest is not None,
        })

    @app.route("/api/queries/<int:query_id>/train", methods=["POST"])
    def train_model(query_id):
        auth_err = check_api_key()
        if auth_err:
            return auth_err
        if not rate_limiter.allow(client_ip(), max_calls=5, window_s=60):
            return jsonify({"error": "rate limit exceeded"}), 429
        if not db.get_query(query_id):
            return jsonify({"error": "Query not found"}), 404
        try:
            result = monitor.train_and_save_model(query_id)
            return jsonify(result)
        except Exception as e:
            logger.exception(f"train_model failed for query {query_id}")
            return jsonify({"error": "training failed", "detail": str(e)[:200]}), 500

    @app.route("/api/queries/<int:query_id>/model_versions", methods=["GET"])
    def model_versions(query_id):
        if not db.get_query(query_id):
            return jsonify({"error": "Query not found"}), 404
        store = monitor.model_store
        versions = store.list_versions(query_id)
        return jsonify(versions)

    @app.route("/api/queries/<int:query_id>/model_rollback", methods=["POST"])
    def model_rollback(query_id):
        auth_err = check_api_key()
        if auth_err:
            return auth_err
        if not rate_limiter.allow(client_ip(), max_calls=5, window_s=60):
            return jsonify({"error": "rate limit exceeded"}), 429
        if not db.get_query(query_id):
            return jsonify({"error": "Query not found"}), 404
        data = request.get_json(silent=True) or {}
        version = data.get("version")
        if not isinstance(version, int) or version < 1:
            return jsonify({"error": "version must be a positive integer"}), 400
        store = monitor.model_store
        success = store.rollback(query_id, version)
        if success:
            return jsonify({"message": f"Rolled back to v{version}", "version": version})
        return jsonify({"error": "rollback failed"}), 400
