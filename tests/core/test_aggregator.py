"""
S2: Unit tests for core/aggregator.py
Tests FlightAggregator static methods and data processing.
"""

import pytest
from unittest.mock import patch
from core.models import FlightPrice, SearchQuery
from core.aggregator import FlightAggregator, AIRCRAFT_DETAILS, _AIRCRAFT_ALIASES


class TestCalcDuration:
    """Tests for _calc_duration static method."""

    def test_normal_flight(self):
        assert FlightAggregator._calc_duration("0800", "1030") == "2h30m"

    def test_overnight_flight(self):
        assert FlightAggregator._calc_duration("2200", "0130") == "3h30m"

    def test_one_hour_flight(self):
        assert FlightAggregator._calc_duration("0800", "0900") == "1h0m"

    def test_empty_input(self):
        assert FlightAggregator._calc_duration("", "1000") == ""

    def test_invalid_input(self):
        assert FlightAggregator._calc_duration("abc", "def") == ""

    def test_colon_format(self):
        assert FlightAggregator._calc_duration("08:00", "10:30") == "2h30m"


class TestSanitizeAirport:
    """Tests for _sanitize_airport static method."""

    def test_city_code_bjs(self):
        assert FlightAggregator._sanitize_airport("BJS", "北京") == "北京"

    def test_city_code_sha(self):
        assert FlightAggregator._sanitize_airport("SHA", "上海") == "上海"

    def test_empty_returns_default(self):
        assert FlightAggregator._sanitize_airport("", "北京") == "北京"

    def test_readable_name_preserved(self):
        assert FlightAggregator._sanitize_airport("北京首都", "北京") == "北京首都"

    def test_numeric_code_preserved(self):
        assert FlightAggregator._sanitize_airport("123", "默认") == "123"


class TestGetPlatformKeys:
    """Tests for _get_platform_keys static method."""

    def test_domestic_route(self):
        keys = FlightAggregator._get_platform_keys("北京", "上海")
        assert "ctrip" in keys
        assert "qunar" in keys
        assert "skyscanner" not in keys

    def test_international_route(self):
        keys = FlightAggregator._get_platform_keys("北京", "东京")
        assert "skyscanner" in keys
        assert "tripcom" in keys
        assert "ctrip" not in keys


class TestAircraftDetails:
    """Tests for aircraft database."""

    def test_known_aircraft(self):
        assert "空客 320" in AIRCRAFT_DETAILS
        assert AIRCRAFT_DETAILS["空客 320"]["manufacturer"] == "Airbus"

    def test_alias_mapping(self):
        assert "a320" in _AIRCRAFT_ALIASES
        assert _AIRCRAFT_ALIASES["a320"] == "空客 320"

    def test_boeing_alias(self):
        assert _AIRCRAFT_ALIASES["b737"] == "波音 737"
