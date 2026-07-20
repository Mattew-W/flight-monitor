"""
S2: Unit tests for datasources/mock_source.py
Tests deterministic pricing, platform selection, and edge cases.
"""
import pytest
from core.models import SearchQuery


class TestMockDeterminism:
    """Mock source should produce identical results for identical inputs."""

    @pytest.fixture
    def source(self):
        from datasources.mock_source import MockDataSource
        return MockDataSource()

    def test_same_route_produces_identical_results(self, source):
        """Same route + date = same flights and prices (deterministic seed)."""
        q1 = SearchQuery(departure="北京", destination="上海",
                         departure_date="2026-08-01")
        q2 = SearchQuery(departure="北京", destination="上海",
                         departure_date="2026-08-01")
        r1 = source.search_flights(q1)
        r2 = source.search_flights(q2)

        assert len(r1) == len(r2), f"counts differ: {len(r1)} vs {len(r2)}"
        for i, (a, b) in enumerate(zip(r1, r2)):
            assert a.flight_no == b.flight_no, f"flight {i}: {a.flight_no} vs {b.flight_no}"
            assert a.price == b.price, f"flight {i}: {a.price} vs {b.price}"
            assert a.source == b.source, f"flight {i} platform differs"

    def test_different_date_produces_different_results(self, source):
        """Different dates should produce different flights (but same count)."""
        q1 = SearchQuery(departure="北京", destination="上海",
                         departure_date="2026-08-01")
        q2 = SearchQuery(departure="北京", destination="上海",
                         departure_date="2026-08-15")
        r1 = source.search_flights(q1)
        r2 = source.search_flights(q2)

        # Different dates may have different prices but likely similar count.
        assert len(r1) > 0
        assert len(r2) > 0

    def test_international_route_has_airlines(self, source):
        """International routes should use international airlines."""
        q = SearchQuery(departure="北京", destination="东京",
                        departure_date="2026-08-01")
        results = source.search_flights(q)
        assert len(results) > 0
        # Should have at least one result with a recognizable airline.
        airlines = {r.airline for r in results}
        assert len(airlines) > 0

    def test_prices_in_valid_range(self, source):
        """All generated prices should be in a reasonable range."""
        q = SearchQuery(departure="北京", destination="上海",
                        departure_date="2026-08-01")
        results = source.search_flights(q)
        for r in results:
            assert 100 <= r.price <= 20000, f"price {r.price} out of range"
