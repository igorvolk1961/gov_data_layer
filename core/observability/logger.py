"""Minimal logging: configurable level, stderr output.

No structlog. The single observability channel is Tracer (see tracer.py).
Errors are duplicated to console for operational visibility.

NOTE: LOG_LEVEL is read lazily from the environment on first call to
get_logger(), so it picks up values loaded by dotenv after import.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

# Корневой логгер ODL — initialised lazily
_odl_logger = logging.getLogger("odl")
_odl_logger.setLevel(logging.ERROR)  # temporary; overridden on first use
_odl_logger.addHandler(logging.NullHandler())  # prevent "No handler found" warnings

# Valid log level names (lowercase) for external consumers (e.g. uvicorn)
VALID_LOG_LEVELS = ("critical", "error", "warning", "info", "debug", "trace")

_configured = False
_lock = threading.Lock()

# Stored effective level name (upper-case), set during _ensure_configured.
# Used by get_effective_level_name() instead of logging.getLevelName()
# to avoid "Level %d" fallback strings for custom numeric levels.
_effective_level_name: str = "ERROR"


def _ensure_configured() -> None:
    """Apply LOG_LEVEL from environment (called once on first get_logger).

    Thread-safe: uses a lock to prevent duplicate handler installation
    when multiple threads call get_logger() simultaneously.
    """
    global _configured, _effective_level_name
    if _configured:
        return
    with _lock:
        if _configured:
            return
        level_name = os.getenv("LOG_LEVEL", "ERROR").upper()
        level = getattr(logging, level_name, None)
        if not isinstance(level, int):
            level = logging.ERROR
            _effective_level_name = "ERROR"
            _odl_logger.warning(
                "Unknown LOG_LEVEL '%s', falling back to ERROR",
                level_name,
            )
        else:
            _effective_level_name = level_name
        _odl_logger.setLevel(level)

        # Remove the temporary NullHandler
        for h in list(_odl_logger.handlers):
            if isinstance(h, logging.NullHandler):
                _odl_logger.removeHandler(h)

        # Консольный handler (stderr)
        _console = logging.StreamHandler(sys.stderr)
        _console.setLevel(level)
        _console.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        _odl_logger.addHandler(_console)
        _configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a child logger for the given module.

    Configures the root ODL logger on first call, reading LOG_LEVEL
    from the environment at that point (so dotenv has had a chance to
    load .env before this is invoked).

    Args:
        name: Module name (typically __name__).

    Returns:
        logging.Logger: logger configured according to LOG_LEVEL env var.
    """
    _ensure_configured()
    return _odl_logger.getChild(name)


def get_effective_level_name() -> str:
    """Return the effective ODL log level name (e.g. 'INFO', 'ERROR').

    Can be used by other components (e.g. uvicorn) to align their log level
    with the ODL logger level.

    Returns:
        Upper-case log level name string.
    """
    return _effective_level_name


def reset_for_testing() -> None:
    """Reset logger to unconfigured state (for testing only).

    Removes all handlers, restores the NullHandler, and clears the
    configured flag so the next call to get_logger() re-initialises.
    """
    global _configured, _effective_level_name
    _configured = False
    _effective_level_name = "ERROR"
    _odl_logger.setLevel(logging.ERROR)
    for h in list(_odl_logger.handlers):
        _odl_logger.removeHandler(h)
    _odl_logger.addHandler(logging.NullHandler())
