"""
Flight Monitor - Structured Logging (S5 Framework)
====================================================
JSON-formatted logs with request_id tracking.

Features:
  - JSON log format for machine parsing
  - request_id injection via Flask middleware
  - Context-aware logging with structlog-style extras
  - File handler with rotation support

Usage:
    # In main.py:
    from core.logging_config import setup_logging
    setup_logging()

    # In Flask routes:
    from core.logging_config import get_logger, request_id
    logger = get_logger(__name__)
    logger.info("request_processed", extra={"request_id": request_id.get()})

    # Or use the middleware (automatic):
    from core.logging_config import setup_request_logging
    setup_request_logging(app)
"""

import logging
import logging.handlers
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Optional

# Context variable for request_id (async-safe, thread-safe)
request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class JSONFormatter(logging.Formatter):
    """Format log records as JSON strings.

    Output format:
        {"timestamp": "...", "level": "INFO", "logger": "...", "message": "...", "request_id": "..."}
    """

    def format(self, record: logging.LogRecord) -> str:
        import json

        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request_id if available
        rid = request_id.get()
        if rid:
            log_entry["request_id"] = rid

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)

        # Add exception info
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class RequestIDFilter(logging.Filter):
    """Inject request_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get() or "-"
        return True


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    json_format: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
):
    """Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file path (if None, logs to stderr only)
        json_format: Use JSON format (True) or plain text (False)
        max_bytes: Max log file size before rotation
        backup_count: Number of rotated log files to keep
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create formatter
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RequestIDFilter())
    root_logger.addHandler(console_handler)

    # File handler (optional, with rotation)
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RequestIDFilter())
        root_logger.addHandler(file_handler)

    logging.info("Logging configured (level=%s, json=%s)", level, json_format)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the standard configuration."""
    return logging.getLogger(name)


def generate_request_id() -> str:
    """Generate a short request ID (first 8 chars of UUID4)."""
    return uuid.uuid4().hex[:8]


def setup_request_logging(app):
    """Add request_id middleware to a Flask app.

    Automatically generates a request_id for each incoming request
    and logs request/response info.
    """
    import time
    from flask import g, request as flask_request

    logger = get_logger("request")

    @app.before_request
    def _inject_request_id():
        # Use X-Request-ID header if provided, otherwise generate one
        rid = flask_request.headers.get("X-Request-ID", generate_request_id())
        request_id.set(rid)
        g.request_id = rid
        g.request_start_time = time.time()

    @app.after_request
    def _log_request(response):
        rid = request_id.get() or "-"
        duration = time.time() - getattr(g, "request_start_time", time.time())
        logger.info(
            f"{flask_request.method} {flask_request.path} "
            f"→ {response.status_code} ({duration:.3f}s)",
            extra={"request_id": rid},
        )
        # Echo request_id in response headers
        response.headers["X-Request-ID"] = rid
        return response
