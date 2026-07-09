"""Minimal logging: ERROR and above to stderr only.

No structlog. The single observability channel is Tracer (see tracer.py).
Errors are duplicated to console for operational visibility.
"""

from __future__ import annotations

import logging
import sys

# Корневой логгер ODL — только ERROR+
_odl_logger = logging.getLogger("odl")
_odl_logger.setLevel(logging.ERROR)

# Консольный handler (stderr)
_console = logging.StreamHandler(sys.stderr)
_console.setLevel(logging.ERROR)
_console.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
)
_odl_logger.addHandler(_console)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger for the given module.

    Args:
        name: Module name (typically __name__).

    Returns:
        logging.Logger: logger configured for ERROR+ to stderr.
    """
    return _odl_logger.getChild(name)
