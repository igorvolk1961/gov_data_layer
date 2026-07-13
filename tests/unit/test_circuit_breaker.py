"""Unit tests for CircuitBreaker."""

from __future__ import annotations

import time

from adapters.base.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitState:
    """CircuitState enum values."""

    def test_enum_values(self) -> None:
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitBreakerInitialState:
    """CircuitBreaker starts in CLOSED state with zero failures."""

    def test_default_parameters(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.is_open is False
        assert cb.can_request() is True

    def test_custom_parameters(self) -> None:
        cb = CircuitBreaker(
            name="test",
            failure_threshold=3,
            recovery_timeout=10.0,
            half_open_max_requests=2,
        )
        assert cb._name == "test"
        assert cb._failure_threshold == 3
        assert cb._recovery_timeout == 10.0
        assert cb._half_open_max_requests == 2


class TestCircuitBreakerStateMachine:
    """State transitions: CLOSED → OPEN → HALF_OPEN → CLOSED."""

    def test_closed_to_open_on_failure_threshold(self) -> None:
        """After failure_threshold consecutive failures, circuit opens."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

        # Record 2 failures — still CLOSED
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 2
        assert cb.can_request() is True

        # 3rd failure → OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3
        assert cb.can_request() is False

    def test_open_fast_fails_requests(self) -> None:
        """When circuit is OPEN, can_request() returns False."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_request() is False

    def test_open_to_half_open_after_timeout(self) -> None:
        """After recovery_timeout, OPEN transitions to HALF_OPEN."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for timeout to elapse
        time.sleep(0.02)

        assert cb.can_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_probe_success_closes_circuit(self) -> None:
        """Successful probe in HALF_OPEN resets to CLOSED."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        # can_request() triggers OPEN → HALF_OPEN transition
        assert cb.can_request() is True
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.can_request() is True

    def test_half_open_probe_failure_reopens_circuit(self) -> None:
        """Failed probe in HALF_OPEN transitions back to OPEN."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        # can_request() triggers OPEN → HALF_OPEN transition
        assert cb.can_request() is True
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 2  # incremented from 1 to 2

    def test_half_open_limits_probe_requests(self) -> None:
        """Only half_open_max_requests probes are allowed in HALF_OPEN."""
        cb = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_max_requests=2,
        )
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        # can_request() triggers OPEN → HALF_OPEN transition
        assert cb.can_request() is True
        assert cb.state == CircuitState.HALF_OPEN

        # First probe allowed
        assert cb.can_request() is True
        # Second probe allowed
        assert cb.can_request() is True
        # Third probe blocked (still HALF_OPEN)
        assert cb.can_request() is False

    def test_reset_returns_to_closed(self) -> None:
        """reset() forces circuit back to CLOSED regardless of state."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.can_request() is True


class TestCircuitBreakerIsOpenProperty:
    """is_open property with auto-transition."""

    def test_is_open_false_when_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.is_open is False

    def test_is_open_true_when_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999.0)
        cb.record_failure()
        assert cb.is_open is True

    def test_is_open_auto_transitions_to_half_open(self) -> None:
        """is_open triggers OPEN → HALF_OPEN transition after timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.02)

        # is_open should return False and transition to HALF_OPEN
        assert cb.is_open is False
        assert cb.state == CircuitState.HALF_OPEN


class TestCircuitBreakerToDict:
    """Serialization for observability."""

    def test_to_dict_initial_state(self) -> None:
        cb = CircuitBreaker(name="test-cb")
        d = cb.to_dict()
        assert d["name"] == "test-cb"
        assert d["state"] == "closed"
        assert d["failure_count"] == 0
        assert d["failure_threshold"] == 5
        assert d["recovery_timeout"] == 30.0
        assert d["last_failure_time"] == 0.0

    def test_to_dict_after_failures(self) -> None:
        cb = CircuitBreaker(name="test-cb", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        d = cb.to_dict()
        assert d["state"] == "closed"
        assert d["failure_count"] == 2
        assert d["last_failure_time"] > 0.0


class TestCircuitBreakerEdgeCases:
    """Edge cases and boundary conditions."""

    def test_single_failure_below_threshold(self) -> None:
        """Single failure below threshold keeps circuit CLOSED."""
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_request() is True

    def test_success_resets_failure_count(self) -> None:
        """A success resets the failure counter."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_success_in_half_open_closes_circuit(self) -> None:
        """record_success in HALF_OPEN transitions to CLOSED."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.can_request() is True
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_failure_in_half_open_reopens(self) -> None:
        """record_failure in HALF_OPEN transitions to OPEN."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.can_request() is True
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_zero_failure_threshold(self) -> None:
        """failure_threshold=0 means every failure opens the circuit."""
        cb = CircuitBreaker(failure_threshold=0, recovery_timeout=999.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_recovery_timeout_zero(self) -> None:
        """recovery_timeout=0 means immediate HALF_OPEN."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # With timeout=0, can_request should immediately transition to HALF_OPEN
        assert cb.can_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_multiple_open_close_cycles(self) -> None:
        """Circuit can go through multiple open/close cycles."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)

        # Cycle 1
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.can_request() is True
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

        # Cycle 2
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.can_request() is True
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
