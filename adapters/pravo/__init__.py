"""PravoAdapter — адаптер для источника данных pravo.gov.ru."""

from adapters.base.circuit_breaker import CircuitBreaker, CircuitState
from adapters.pravo.adapter import PravoAdapter
from adapters.pravo.pravo_client import PravoClient
from adapters.pravo.pravo_parser import PravoParser

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "PravoAdapter",
    "PravoClient",
    "PravoParser",
]
