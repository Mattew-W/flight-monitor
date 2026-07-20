"""
Flight Monitor - Main Entry Point
Launches the web application and starts the price monitoring engine.
"""
import logging
import signal
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DB_PATH, HOST, PORT, DEBUG
from core.database import Database
from core.monitor import PriceMonitor
from core.logging_config import setup_logging
from api.routes import create_app

# Configure structured logging (S5: JSON format + request_id support)
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
setup_logging(level="INFO", log_file=os.path.join(LOG_DIR, "flight_monitor.log"))
logger = logging.getLogger("flight_monitor")


def _shutdown(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    # The finally block in main() will handle cleanup
    raise SystemExit(0)


def _progress(step: int, total: int, msg: str):
    """Print a simple startup progress bar to the console."""
    filled = int(30 * step / total)
    bar = "█" * filled + "░" * (30 - filled)
    print(f"\r  [{bar}] {step}/{total} {msg}", end="", flush=True)
    if step == total:
        print()  # newline at 100%


def main():
    """Start the flight monitor application."""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    TOTAL = 5
    logger.info("=" * 60)
    logger.info("  Flight Price Monitor - Starting...")
    logger.info("=" * 60)

    _progress(1, TOTAL, "初始化数据库...")
    # Initialize database
    db = Database(DB_PATH)
    logger.info(f"Database initialized: {DB_PATH}")

    _progress(2, TOTAL, "初始化监控引擎（加载数据源）...")
    # Initialize monitor
    monitor = PriceMonitor(db)
    logger.info(f"Data sources: {list(monitor.sources.keys())}")

    _progress(3, TOTAL, "创建 Web 服务...")
    # Create Flask app
    app = create_app(db, monitor)

    _progress(4, TOTAL, "检查监控任务...")
    # Auto-start monitor if there are monitoring queries
    monitoring_queries = db.get_monitoring_queries()
    if monitoring_queries:
        logger.info(f"Found {len(monitoring_queries)} monitoring queries, auto-starting monitor...")
        monitor.start()
    else:
        logger.info("No monitoring queries found. Monitor will start when you add tasks.")

    _progress(5, TOTAL, "启动完成！")
    # Run Flask
    logger.info(f"Web UI: http://{HOST}:{PORT}")
    logger.info("Press Ctrl+C to stop.")
    logger.info("-" * 60)

    try:
        app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        logger.info("Shutting down monitor...")
        monitor.stop()
        # Close ALL thread-local connections (not just this thread's).
        try:
            db.close_all()
        except Exception as e:
            logger.warning(f"db.close_all() error: {e}")
        logger.info("Goodbye!")


if __name__ == "__main__":
    main()
