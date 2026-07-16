"""
S2: Unit tests for core/database.py
Tests database operations, connection management, and CRUD.
"""

import pytest
from core.database import Database
from core.models import SearchQuery, FlightPrice, PriceAlert


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_memory_db_creation(self, memory_db):
        assert memory_db is not None

    def test_create_tables(self, memory_db):
        """Tables should be created on init."""
        conn = memory_db._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [row[0] for row in tables]
        assert "price_records" in table_names
        assert "search_queries" in table_names
        assert "price_alerts" in table_names


class TestSearchQueries:
    """Tests for search query CRUD operations."""

    def test_add_and_get_query(self, memory_db, sample_query):
        qid = memory_db.add_query(sample_query)
        assert qid is not None
        assert qid > 0

    def test_get_monitoring_queries(self, memory_db, sample_query):
        sample_query.is_monitoring = True
        memory_db.add_query(sample_query)
        queries = memory_db.get_monitoring_queries()
        assert len(queries) >= 1

    def test_get_all_queries(self, memory_db, sample_query):
        memory_db.add_query(sample_query)
        queries = memory_db.get_all_queries()
        assert len(queries) >= 1

    def test_update_monitoring(self, memory_db, sample_query):
        qid = memory_db.add_query(sample_query)
        memory_db.update_query_monitoring(qid, True)
        queries = memory_db.get_monitoring_queries()
        assert any(q.id == qid for q in queries)


class TestPriceRecords:
    """Tests for price record operations."""

    def test_add_price_record(self, memory_db, sample_query, sample_flight):
        qid = memory_db.add_query(sample_query)
        sample_flight.query_id = qid
        memory_db.add_price_records([sample_flight])
        conn = memory_db._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM price_records").fetchone()[0]
        assert count >= 1

    def test_add_multiple_prices(self, memory_db, sample_query, sample_flights):
        qid = memory_db.add_query(sample_query)
        for f in sample_flights:
            f.query_id = qid
        memory_db.add_price_records(sample_flights)
        conn = memory_db._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM price_records").fetchone()[0]
        assert count == 3

    def test_get_historical_prices(self, memory_db, sample_query, sample_flights):
        from core.price_prediction import get_historical_prices
        qid = memory_db.add_query(sample_query)
        for f in sample_flights:
            f.query_id = qid
        memory_db.add_price_records(sample_flights)
        # real_only=False because test data uses source="test", not "ctrip_browser"
        prices = get_historical_prices(memory_db, query_id=qid, days_back=30, real_only=False)
        assert len(prices) >= 1


class TestAlerts:
    """Tests for alert operations."""

    def test_add_alert(self, memory_db, sample_query, sample_alert):
        qid = memory_db.add_query(sample_query)
        sample_alert.query_id = qid
        aid = memory_db.add_alert(sample_alert)
        assert aid is not None

    def test_get_alerts(self, memory_db, sample_query, sample_alert):
        qid = memory_db.add_query(sample_query)
        sample_alert.query_id = qid
        memory_db.add_alert(sample_alert)
        alerts = memory_db.get_alerts(qid)
        assert len(alerts) >= 1
