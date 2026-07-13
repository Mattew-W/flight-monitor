"""
Flight Monitor - Main Entry Point
Launches the web application and starts the price monitoring engine.
"""
import logging
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DB_PATH, HOST, PORT, DEBUG
from core.database import Database
from core.monitor import PriceMonitor
from api.routes import create_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("flight_monitor")


def main():
    """Start the flight monitor application."""
    logger.info("=" * 60)
    logger.info("  Flight Price Monitor - Starting...")
    logger.info("=" * 60)

    # Initialize database
    db = Database(DB_PATH)
    logger.info(f"Database initialized: {DB_PATH}")

    # Initialize monitor
    monitor = PriceMonitor(db)
    logger.info(f"Data sources: {list(monitor.sources.keys())}")

    # Create Flask app
    app = create_app(db, monitor)

    # Auto-start monitor if there are monitoring queries
    monitoring_queries = db.get_monitoring_queries()
    if monitoring_queries:
        logger.info(f"Found {len(monitoring_queries)} monitoring queries, auto-starting monitor...")
        monitor.start()
    else:
        logger.info("No monitoring queries found. Monitor will start when you add tasks.")

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
        logger.info("Goodbye!")


if __name__ == "__main__":
    main()
