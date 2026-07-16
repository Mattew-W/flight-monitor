"""
S2: Unit tests for core/source_chain.py
Tests source chain ordering, fallback behavior, and circuit breaker integration.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from core.source_chain import SourceChain, SourceEntry
from core.models import SearchQuery, FlightPrice


class TestSourceChainInit:
    """Tests for source chain initialization."""

    def test_empty_chain(self):
        chain = SourceChain("test")
        assert len(chain) == 0
        assert chain.get_source_names() == []

    def test_add_source(self):
        chain = SourceChain("test")
        mock_source = MagicMock()
        mock_source.name = "mock"
        chain.add_source(mock_source, priority=1)
        assert len(chain) == 1
        assert chain.get_source_names() == ["mock"]

    def test_priority_ordering(self):
        chain = SourceChain("test")
        src1 = MagicMock()
        src1.name = "low_priority"
        src2 = MagicMock()
        src2.name = "high_priority"
        src3 = MagicMock()
        src3.name = "mid_priority"

        chain.add_source(src1, priority=10)
        chain.add_source(src2, priority=1)
        chain.add_source(src3, priority=5)

        names = chain.get_source_names()
        assert names == ["high_priority", "mid_priority", "low_priority"]


class TestSourceChainSearch:
    """Tests for source chain search behavior."""

    @pytest.mark.asyncio
    async def test_first_source_succeeds(self):
        chain = SourceChain("test")
        query = SearchQuery(departure="北京", destination="上海")

        # First source returns results
        src1 = MagicMock()
        src1.name = "src1"
        src1.is_available.return_value = True
        src1.search_flights.return_value = [
            FlightPrice(flight_no="CA123", price=500.0)
        ]

        # Second source should not be called
        src2 = MagicMock()
        src2.name = "src2"
        src2.is_available.return_value = True

        chain.add_source(src1, priority=1)
        chain.add_source(src2, priority=2)

        results = await chain.search(query)
        assert len(results) == 1
        assert results[0].flight_no == "CA123"
        src2.search_flights.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_to_second_source(self):
        chain = SourceChain("test")
        query = SearchQuery(departure="北京", destination="上海")

        # First source returns empty
        src1 = MagicMock()
        src1.name = "src1"
        src1.is_available.return_value = True
        src1.search_flights.return_value = []

        # Second source returns results
        src2 = MagicMock()
        src2.name = "src2"
        src2.is_available.return_value = True
        src2.search_flights.return_value = [
            FlightPrice(flight_no="MU456", price=600.0)
        ]

        chain.add_source(src1, priority=1)
        chain.add_source(src2, priority=2)

        results = await chain.search(query)
        assert len(results) == 1
        assert results[0].flight_no == "MU456"

    @pytest.mark.asyncio
    async def test_all_sources_fail_returns_empty(self):
        chain = SourceChain("test")
        query = SearchQuery(departure="北京", destination="上海")

        src1 = MagicMock()
        src1.name = "src1"
        src1.is_available.return_value = True
        src1.search_flights.side_effect = Exception("Connection error")

        chain.add_source(src1, priority=1)

        results = await chain.search(query)
        assert results == []

    @pytest.mark.asyncio
    async def test_unavailable_source_skipped(self):
        chain = SourceChain("test")
        query = SearchQuery(departure="北京", destination="上海")

        src1 = MagicMock()
        src1.name = "unavailable"
        src1.is_available.return_value = False

        src2 = MagicMock()
        src2.name = "available"
        src2.is_available.return_value = True
        src2.search_flights.return_value = [
            FlightPrice(flight_no="CZ789", price=700.0)
        ]

        chain.add_source(src1, priority=1)
        chain.add_source(src2, priority=2)

        results = await chain.search(query)
        assert len(results) == 1
        src1.search_flights.assert_not_called()


class TestSourceChainStats:
    """Tests for source chain statistics."""

    def test_stats_tracking(self):
        chain = SourceChain("test")
        mock_source = MagicMock()
        mock_source.name = "mock"
        chain.add_source(mock_source, priority=1)

        stats = chain.get_stats()
        assert "mock" in stats
        assert stats["mock"]["success"] == 0
        assert stats["mock"]["failure"] == 0
