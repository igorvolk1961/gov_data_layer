"""CircuitBreaker — generic circuit breaker pattern for external API calls.

Implements the standard circuit breaker state machine:
- CLOSED: normal operation, requests pass through
- OPEN: failures threshold exceeded, requests are fast-failed
- HALF_OPEN: after timeout, one probe request is allowed

State transitions:
  CLOSED → OPEN: failure_count >= failure_threshold
  OPEN → HALF_OPEN: after recovery_timeout seconds
  HALF_OPEN → CLOSED: probe request succeeds
  HALF_OPEN → OPEN: probe request fails
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from core.observability.logger import get_logger

logger = get_logger(__name__)

# Default circuit breaker parameters
_DEFAULT_FAILURE_THRESHOLD = 5
_DEFAULT_RECOVERY_TIMEOUT = 30.0
_DEFAULT_HALF_OPEN_MAX_REQUESTS = 1


class CircuitState(str, Enum):
    """Состояние circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker for external API calls.

    Tracks consecutive failures and opens the circuit when the threshold
    is exceeded. After a recovery timeout, transitions to HALF_OPEN to
    allow a probe request. If the probe succeeds, the circuit closes;
    otherwise it re-opens.

    Thread-safe for asyncio usage (single-threaded event loop).
    """

    def __init__(
        self,
        *,
        name: str = "default",
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout: float = _DEFAULT_RECOVERY_TIMEOUT,
        half_open_max_requests: int = _DEFAULT_HALF_OPEN_MAX_REQUESTS,
    ) -> None:
        """Initialize CircuitBreaker.

        Args:
            name: Name for logging/tracing.
            failure_threshold: Consecutive failures before opening.
            recovery_timeout: Seconds to wait before HALF_OPEN.
            half_open_max_requests: Max probe requests in HALF_OPEN state.
        """
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_requests = half_open_max_requests

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_requests: int = 0

    # ── Properties ──────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        """Current circuit breaker state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._failure_count

    @property
    def is_open(self) -> bool:
        """Whether the circuit is currently open (fast-fail)."""
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed → transition to HALF_OPEN
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_requests = 0
                logger.info(
                    "Circuit [%s] transitioned OPEN → HALF_OPEN after %.1fs timeout",
                    self._name,
                    self._recovery_timeout,
                )
                return False
            return True
        return False

    # ── Public API ──────────────────────────────────────────────

    def can_request(self) -> bool:
        """Check if a request is allowed through the circuit.

        Returns:
            True if the request should proceed, False if fast-failed.
        """
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # Check recovery timeout
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_requests = 0
                logger.info(
                    "Circuit [%s] transitioned OPEN → HALF_OPEN (can_request)",
                    self._name,
                )
                return True
            return False

        # HALF_OPEN: allow limited probe requests
        if self._half_open_requests < self._half_open_max_requests:
            self._half_open_requests += 1
            return True

        return False

    def record_success(self) -> None:
        """Record a successful request.

        Resets failure count and closes the circuit if in HALF_OPEN.
        """
        if self._state == CircuitState.HALF_OPEN:
            logger.info(
                "Circuit [%s] transitioned HALF_OPEN → CLOSED (probe succeeded)",
                self._name,
            )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_requests = 0

    def record_failure(self) -> None:
        """Record a failed request.

        Increments failure count. If threshold exceeded, opens the circuit.
        """
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning(
                "Circuit [%s] transitioned HALF_OPEN → OPEN (probe failed, %d/%d failures)",
                self._name,
                self._failure_count,
                self._failure_threshold,
            )
            self._state = CircuitState.OPEN
            return

        if self._failure_count >= self._failure_threshold:
            logger.warning(
                "Circuit [%s] transitioned CLOSED → OPEN (%d/%d failures)",
                self._name,
                self._failure_count,
                self._failure_threshold,
            )
            self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Force-reset the circuit to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_requests = 0
        logger.info("Circuit [%s] reset to CLOSED", self._name)

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for observability/tracing.

        Returns:
            Dict with current circuit state.
        """
        return {
            "name": self._name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "recovery_timeout": self._recovery_timeout,
            "last_failure_time": self._last_failure_time,
        }


__all__ = [
    "CircuitBreaker",
    "CircuitState",
]
