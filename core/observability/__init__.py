"""Observability: unified Tracer (LangFuse + FileFallback).

Usage:
    from core.observability import configure, get_tracer, get_logger

    # On application startup:
    config = ObservabilityConfig.from_env()
    configure(config)

    # In any module:
    tracer = get_tracer()
    logger = get_logger(__name__)

    with tracer.trace("operation") as span:
        span.set_input({"key": "value"})
        result = do_work()
        span.set_output({"result": result})
"""

from core.observability.config import ObservabilityConfig
from core.observability.logger import get_logger
from core.observability.tracer import (
    FileFallbackTracer,
    LangFuseTracer,
    Tracer,
    create_tracer,
    get_tracer,
    set_tracer,
)

__all__ = [
    "FileFallbackTracer",
    "LangFuseTracer",
    "ObservabilityConfig",
    "Tracer",
    "create_tracer",
    "get_logger",
    "get_tracer",
    "set_tracer",
]


def configure(config: ObservabilityConfig | None = None) -> Tracer:
    """Configure the observability layer on application startup.

    Args:
        config: Configuration. If None, reads from environment variables.

    Returns:
        Tracer: ready-to-use implementation (LangFuseTracer or FileFallbackTracer).
    """
    if config is None:
        config = ObservabilityConfig.from_env()
    tracer = create_tracer(config)
    set_tracer(tracer)
    return tracer
