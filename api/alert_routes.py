"""
Flight Monitor API — Alert Routes
"""
from flask import request, jsonify
from core.models import PriceAlert


def register(app, db, monitor):
    """Register all alert-related routes."""

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
                "notify_feishu": a.notify_feishu,
                "created_at": a.created_at,
                "last_triggered": a.last_triggered,
                "query_label": q.label if q else "",
                "query_route": f"{q.departure}->{q.destination}" if q else "",
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
        q = db.get_query(data["query_id"])
        if not q:
            return jsonify({"error": "Query not found"}), 404
        alert = PriceAlert(
            query_id=data["query_id"],
            target_price=target_price,
            is_active=data.get("is_active", True),
            notify_email=data.get("notify_email", True),
            notify_wechat=data.get("notify_wechat", False),
            notify_feishu=data.get("notify_feishu", True),
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
