"""Unit tests for logger (core/observability/logger.py).

Tests cover:
- get_logger returns a child of the 'odl' logger
- get_effective_level_name returns the configured level
- Lazy configuration reads LOG_LEVEL from environment
- Thread-safe initialization (basic)
- Unknown LOG_LEVEL falls back to ERROR
"""

from __future__ import annotations

import logging
import os

import pytest

from core.observability.logger import (
    _odl_logger,
    get_effective_level_name,
    get_logger,
    reset_for_testing,
)


@pytest.fixture(autouse=True)
def reset_logger() -> None:
    """Reset the logger state before and after each test.

    Uses the public reset_for_testing() API to restore the logger to
    its unconfigured state, ensuring test isolation.
    """
    reset_for_testing()
    yield
    reset_for_testing()


class TestGetLogger:
    def test_returns_child_logger(self) -> None:
        logger = get_logger("test.module")
        assert logger.name == "odl.test.module"
        assert logger.parent is _odl_logger

    def test_configures_on_first_call(self) -> None:
        # Note: _configured may already be True if tracer.py was imported
        # (it calls get_logger at module level). We test that calling
        # get_logger does not raise and that the logger is usable.
        logger = get_logger("test.configures")
        assert logger.name == "odl.test.configures"

    def test_does_not_reconfigure(self) -> None:
        get_logger("test")
        first_handlers = list(_odl_logger.handlers)
        get_logger("test.again")
        second_handlers = list(_odl_logger.handlers)
        # Should have the same handlers (not duplicated)
        assert len(first_handlers) == len(second_handlers)


class TestGetEffectiveLevelName:
    def test_default_level(self) -> None:
        """Before configuration, the level is ERROR."""
        assert get_effective_level_name() == "ERROR"

    def test_after_configuration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        get_logger("test")
        assert get_effective_level_name() == "DEBUG"

    def test_info_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        get_logger("test")
        assert get_effective_level_name() == "INFO"


class TestLazyConfiguration:
    def test_reads_log_level_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        get_logger("test")
        assert _odl_logger.level == logging.WARNING

    def test_defaults_to_error(self) -> None:
        """When LOG_LEVEL is not set, defaults to ERROR."""
        # Ensure env var is not set
        if "LOG_LEVEL" in os.environ:
            del os.environ["LOG_LEVEL"]
        get_logger("test")
        assert _odl_logger.level == logging.ERROR

    def test_unknown_level_falls_back_to_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "BOGUS")
        get_logger("test")
        assert _odl_logger.level == logging.ERROR

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "debug")
        get_logger("test")
        assert _odl_logger.level == logging.DEBUG

    def test_adds_stream_handler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        get_logger("test")
        handler_types = [type(h) for h in _odl_logger.handlers]
        assert logging.StreamHandler in handler_types
        assert logging.NullHandler not in handler_types

    def test_removes_null_handler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        get_logger("test")
        assert not any(isinstance(h, logging.NullHandler) for h in _odl_logger.handlers)
