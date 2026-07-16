"""
S2: Unit tests for core/models.py
Tests data model validation, sanitization, and edge cases.
"""

import math
import pytest
from core.models import SearchQuery, FlightPrice, PriceAlert, AlertHistory


class TestSearchQuery:
    """Tests for SearchQuery dataclass."""

    def test_create_basic(self, sample_query):
        assert sample_query.departure == "北京"
        assert sample_query.destination == "上海"
        assert sample_query.departure_date == "2026-08-01"

    def test_default_values(self):
        q = SearchQuery()
        assert q.departure == ""
        assert q.cabin_class == "economy"
        assert q.trip_type == "oneway"
        assert q.is_monitoring is False

    def test_optional_id(self, sample_query):
        assert sample_query.id == 1
        q2 = SearchQuery()
        assert q2.id is None


class TestFlightPrice:
    """Tests for FlightPrice dataclass with validation."""

    def test_create_basic(self, sample_flight):
        assert sample_flight.flight_no == "CA1501"
        assert sample_flight.price == 850.0
        assert sample_flight.airline == "中国国航"

    def test_nan_price_sanitized(self):
        """NaN price should be clamped to 0.0."""
        fp = FlightPrice(price=float("nan"))
        assert fp.price == 0.0

    def test_negative_price_sanitized(self):
        """Negative price should be clamped to 0.0."""
        fp = FlightPrice(price=-100.0)
        assert fp.price == 0.0

    def test_none_price_preserved(self):
        """None price should remain None (not crash)."""
        fp = FlightPrice(price=None)
        assert fp.price is None

    def test_valid_price_unchanged(self):
        """Valid positive price should not be modified."""
        fp = FlightPrice(price=999.0)
        assert fp.price == 999.0

    def test_zero_price_allowed(self):
        """Zero price is valid (used as sentinel)."""
        fp = FlightPrice(price=0.0)
        assert fp.price == 0.0

    def test_is_mock_flag(self, sample_flight):
        assert sample_flight.is_mock is False
        mock_fp = FlightPrice(is_mock=True)
        assert mock_fp.is_mock is True


class TestPriceAlert:
    """Tests for PriceAlert dataclass."""

    def test_create_basic(self, sample_alert):
        assert sample_alert.target_price == 800.0
        assert sample_alert.is_active is True
        assert sample_alert.notify_email is True

    def test_default_inactive(self):
        a = PriceAlert()
        assert a.is_active is True
        assert a.target_price == 0.0


class TestAlertHistory:
    """Tests for AlertHistory dataclass."""

    def test_create_basic(self):
        h = AlertHistory(
            alert_id=1, query_id=1, price=750.0, target_price=800.0,
            airline="中国国航", flight_no="CA1501",
        )
        assert h.price == 750.0
        assert h.alert_id == 1
