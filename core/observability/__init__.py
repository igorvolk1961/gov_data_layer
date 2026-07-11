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
from core.observability.configure import configure
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
    "configure",
    "create_tracer",
    "get_logger",
    "get_tracer",
    "set_tracer",
]
