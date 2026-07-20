"""
S2: Unit tests for core/monitor.py
Tests start/stop lifecycle, price filtering, and model training guardrails.
"""
import pytest
from core.models import SearchQuery


class TestMonitorLifecycle:
    """Tests for PriceMonitor start/stop state machine."""

    @pytest.fixture
    def monitor(self, memory_db):
        from core.monitor import PriceMonitor
        return PriceMonitor(memory_db)

    def test_initial_state_not_running(self, monitor):
        """Monitor should not be running initially."""
        assert not monitor.is_running

    def test_start_sets_running(self, monitor):
        """start() should set _running and create a thread."""
        monitor.start()
        assert monitor.is_running
        monitor.stop()

    def test_stop_clears_running(self, monitor):
        """stop() should clear _running state."""
        monitor.start()
        monitor.stop()
        assert not monitor.is_running

    def test_double_start_does_not_crash(self, monitor):
        """Calling start() twice should not create duplicate threads."""
        monitor.start()
        monitor.start()  # should be idempotent
        monitor.stop()
        assert not monitor.is_running

    def test_double_stop_does_not_crash(self, monitor):
        """Calling stop() on already-stopped monitor should be safe."""
        monitor.start()
        monitor.stop()
        monitor.stop()  # should not raise
        assert not monitor.is_running


class TestModelTrainingGuardrails:
    """Tests for train_and_save_model validation."""

    @pytest.fixture
    def monitor(self, memory_db):
        from core.monitor import PriceMonitor
        return PriceMonitor(memory_db)

    def test_insufficient_data_rejected(self, monitor, memory_db):
        """Model training should fail gracefully with < 10 records."""
        # Create a query with NO price records.
        qid = memory_db.add_query(SearchQuery(
            departure="北京", destination="上海", departure_date="2026-08-01"
        ))
        result = monitor.train_and_save_model(qid)
        assert "error" in result or "insufficient" in result.get("status", "")

    def test_training_uses_real_data_only(self, monitor, memory_db,
                                            monkeypatch):
        """train_and_save_model should use real_only=True, include_mock=False."""
        qid = memory_db.add_query(SearchQuery(
            departure="北京", destination="上海", departure_date="2026-08-01"
        ))
        captured_kwargs = {}
        original = memory_db.get_daily_cheapest_records

        def _capture(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return original(*args, **kwargs)

        monkeypatch.setattr(memory_db, "get_daily_cheapest_records", _capture)
        monitor.train_and_save_model(qid)
        assert captured_kwargs.get("real_only") is True
        assert captured_kwargs.get("include_mock") is False
