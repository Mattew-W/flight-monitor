"""
S2: Unit tests for core/circuit_breaker.py
Tests circuit breaker state transitions and thresholds.
"""

import time
import pytest
from core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState


class TestCircuitBreakerInit:
    """Tests for circuit breaker initialization."""

    def test_default_state_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    def test_can_execute_when_closed(self):
        cb = CircuitBreaker("test")
        assert cb.can_execute() is True

    def test_custom_config(self):
        config = CircuitBreakerConfig(failure_threshold=5, recovery_timeout=300)
        cb = CircuitBreaker("test", config)
        assert cb.config.failure_threshold == 5
        assert cb.config.recovery_timeout == 300


class TestCircuitBreakerTransitions:
    """Tests for state transitions."""

    def test_opens_after_threshold_failures(self):
        config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=600)
        cb = CircuitBreaker("test", config)

        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_cannot_execute_when_open(self):
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=600)
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        assert cb.can_execute() is False

    def test_half_open_after_timeout(self):
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_after_success_in_half_open(self):
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_reset(self):
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=600)
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True


class TestCircuitBreakerStats:
    """Tests for statistics and info."""

    def test_get_info(self):
        cb = CircuitBreaker("test")
        info = cb.get_info()
        assert info["name"] == "test"
        assert info["state"] == "closed"
        assert info["failure_count"] == 0

    def test_failure_count_tracking(self):
        config = CircuitBreakerConfig(failure_threshold=5, recovery_timeout=600)
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 2
