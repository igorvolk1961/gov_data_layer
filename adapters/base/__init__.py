"""SourceAdapter Protocol, RSSAdapter base class, CircuitBreaker — контракты и утилиты для адаптеров."""

from adapters.base.circuit_breaker import CircuitBreaker, CircuitState
from adapters.base.rss_adapter import RSSAdapter
from adapters.base.source_adapter import SourceAdapter

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "RSSAdapter",
    "SourceAdapter",
]
