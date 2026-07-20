"""
Flight Monitor — Flask App Factory

Centralised app creation. Routes are registered from sub-modules
(api/query_routes, api/alert_routes, api/flight_routes, api/dashboard_routes).
"""
import logging
import os
from flask import Flask, request, jsonify
from core.database import Database
from core.monitor import PriceMonitor
from core.logging_config import setup_request_logging
from api import _shared as api_shared
from config import DB_PATH

logger = logging.getLogger(__name__)


def create_app(db: Database = None, monitor: PriceMonitor = None) -> Flask:
    """Create and configure the Flask application."""
    _base = os.path.dirname(__file__)
    _parent = os.path.dirname(_base)

    if not api_shared.API_KEY:
        logger.warning(
            "[WARN] FLIGHT_MONITOR_API_KEY is not set. "
            "Write endpoints are open to all requests. "
            "Set API_KEY to enable protection."
        )

    app = Flask(
        __name__,
        template_folder=os.path.join(_base, "..", "templates"),
        static_folder=os.path.join(_base, "..", "static"),
    )

    if db is None:
        db = Database(DB_PATH)
    if monitor is None:
        monitor = PriceMonitor(db)

    app.config["db"] = db
    app.config["monitor"] = monitor

    # S5: structured request logging
    setup_request_logging(app)

    # ── CORS + error handlers ─────────────────────────────────
    @app.after_request
    def _add_cors_headers(resp):
        if api_shared.CORS_ORIGIN:
            resp.headers["Access-Control-Allow-Origin"] = api_shared.CORS_ORIGIN
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
        logger.exception("Unhandled 500 error")
        return jsonify({"error": "internal server error"}), 500

    # ── Write-endpoint auth ───────────────────────────────────
    @app.before_request
    def _enforce_write_auth():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        if not request.path.startswith("/api/"):
            return None
        if not api_shared.API_KEY:
            return None
        resp = None
        if request.method in ("POST", "PUT", "DELETE"):
            resp = api_shared.check_api_key()
        return resp

    # ── Register route modules ────────────────────────────────
    from api.dashboard_routes import register as _reg_dashboard
    from api.query_routes import register as _reg_query
    from api.alert_routes import register as _reg_alert
    from api.flight_routes import register as _reg_flight

    _reg_dashboard(app, db, monitor)
    _reg_query(app, db, monitor)
    _reg_alert(app, db, monitor)
    _reg_flight(app, db, monitor)

    return app
