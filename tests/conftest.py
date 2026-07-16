"""
Flight Monitor - Test Fixtures (S2 Framework)
==============================================
Shared pytest fixtures for unit and integration tests.

Fixtures provided:
    - temp_db: In-memory SQLite database for isolated tests
    - sample_query: A standard SearchQuery for testing
    - sample_flight: A standard FlightPrice for testing
    - mock_data_source: Pre-configured MockDataSource
    - flask_client: Flask test client for API tests
"""

import os
import sys
import math
import pytest
from typing import List

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import Database
from core.models import SearchQuery, FlightPrice, PriceAlert


# ── Database Fixtures ──────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary in-memory database for isolated tests."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    yield db
    db.close_all()


@pytest.fixture
def memory_db():
    """Create an in-memory SQLite database (fastest, no disk I/O)."""
    db = Database(":memory:")
    yield db
    db.close_all()


# ── Model Fixtures ─────────────────────────────────────────────

@pytest.fixture
def sample_query():
    """A standard search query for testing."""
    return SearchQuery(
        id=1,
        departure="北京",
        destination="上海",
        departure_date="2026-08-01",
        cabin_class="economy",
        trip_type="oneway",
    )


@pytest.fixture
def sample_flight():
    """A standard flight price record for testing."""
    return FlightPrice(
        id=1,
        query_id=1,
        airline="中国国航",
        flight_no="CA1501",
        aircraft="A320",
        departure_time="08:00",
        arrival_time="10:30",
        departure_airport="北京",
        arrival_airport="上海",
        duration="2h30m",
        stops=0,
        price=850.0,
        cabin_class="economy",
        source="test",
        recorded_at="2026-07-15T12:00:00",
        purchase_url="https://example.com/book",
        is_mock=False,
        sub_class="Y",
        seat_inventory=9,
    )


@pytest.fixture
def sample_flights(sample_query):
    """A list of sample flight prices for testing."""
    return [
        FlightPrice(
            query_id=sample_query.id or 1,
            airline="中国国航",
            flight_no="CA1501",
            price=850.0,
            source="test",
            recorded_at="2026-07-15T12:00:00",
        ),
        FlightPrice(
            query_id=sample_query.id or 1,
            airline="东方航空",
            flight_no="MU5101",
            price=920.0,
            source="test",
            recorded_at="2026-07-15T12:00:00",
        ),
        FlightPrice(
            query_id=sample_query.id or 1,
            airline="南方航空",
            flight_no="CZ3101",
            price=780.0,
            source="test",
            recorded_at="2026-07-15T12:00:00",
        ),
    ]


@pytest.fixture
def sample_alert():
    """A standard price alert for testing."""
    return PriceAlert(
        id=1,
        query_id=1,
        target_price=800.0,
        is_active=True,
        notify_email=True,
        notify_wechat=False,
    )


# ── Data Source Fixtures ───────────────────────────────────────

@pytest.fixture
def mock_data_source():
    """Pre-configured MockDataSource."""
    from datasources.mock_source import MockDataSource
    return MockDataSource()


# ── Flask Test Client ──────────────────────────────────────────

@pytest.fixture
def flask_client(memory_db):
    """Flask test client for API endpoint testing."""
    from api.routes import create_app
    from core.monitor import PriceMonitor

    monitor = PriceMonitor(memory_db)
    app = create_app(memory_db, monitor)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ── Helpers ────────────────────────────────────────────────────

class TestHelpers:
    """Utility methods available in tests via `helpers` fixture."""

    @staticmethod
    def assert_valid_price(price: FlightPrice):
        """Assert a FlightPrice has valid price (not NaN, not negative)."""
        assert price.price is not None
        assert not math.isnan(price.price)
        assert price.price > 0

    @staticmethod
    def assert_valid_prices(prices: List[FlightPrice]):
        """Assert all prices in a list are valid."""
        for p in prices:
            TestHelpers.assert_valid_price(p)


@pytest.fixture
def helpers():
    """Access to test helper methods."""
    return TestHelpers
