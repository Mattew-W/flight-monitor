"""
Flight Monitor - Circuit Breaker (S4 Framework)
================================================
Implements the Circuit Breaker pattern for data source health management.

States:
    CLOSED   → normal operation, requests pass through
    OPEN     → source is unhealthy, requests blocked
    HALF_OPEN → testing if source has recovered

Transitions:
    CLOSED → OPEN: after `failure_threshold` consecutive failures
    OPEN → HALF_OPEN: after `recovery_timeout` seconds
    HALF_OPEN → CLOSED: on first success
    HALF_OPEN → OPEN: on next failure

Usage:
    config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=600)
    cb = CircuitBreaker("ctrip_browser", config)

    if cb.can_execute():
        try:
            result = do_work()
            cb.record_success()
        except Exception:
            cb.record_failure()
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for a CircuitBreaker instance."""
    failure_threshold: int = 3        # consecutive failures before opening
    recovery_timeout: float = 600.0   # seconds before testing recovery (10 min)
    success_threshold: int = 1         # successes in half_open to close


class CircuitBreaker:
    """Circuit breaker for protecting against repeated failures.

    Thread-safe via simple attribute access (GIL-protected in CPython).
    For high-concurrency scenarios, add a threading.Lock.
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._last_state_change = time.time()

    @property
    def state(self) -> CircuitState:
        """Current state, with automatic transition from OPEN to HALF_OPEN."""
        if (self._state == CircuitState.OPEN
                and time.time() - self._last_failure_time >= self.config.recovery_timeout):
            self._transition(CircuitState.HALF_OPEN)
        return self._state

    @property
    def is_open(self) -> bool:
        """True if circuit is open (requests blocked)."""
        return self.state == CircuitState.OPEN

    def can_execute(self) -> bool:
        """Check if a request should be allowed through."""
        return self.state != CircuitState.OPEN

    def record_success(self):
        """Record a successful operation."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition(CircuitState.CLOSED)
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0  # reset consecutive failures

    def record_failure(self):
        """Record a failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
        elif (self._state == CircuitState.CLOSED
              and self._failure_count >= self.config.failure_threshold):
            self._transition(CircuitState.OPEN)

    def _transition(self, new_state: CircuitState):
        """Transition to a new state with logging."""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()

        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
        elif new_state == CircuitState.OPEN:
            self._success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._success_count = 0

        logger.warning(
            f"CircuitBreaker[{self.name}]: {old_state.value} → {new_state.value} "
            f"(failures={self._failure_count})"
        )

    def reset(self):
        """Manually reset to CLOSED state."""
        self._transition(CircuitState.CLOSED)

    def get_info(self) -> dict:
        """Return current state info for monitoring."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "last_failure_time": self._last_failure_time,
            "last_state_change": self._last_state_change,
        }

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker({self.name}, state={self.state.value}, "
            f"failures={self._failure_count})"
        )
