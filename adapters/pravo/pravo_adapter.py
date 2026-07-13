"""PravoAdapter — адаптер для источника данных pravo.gov.ru.

Thin re-export facade for backward compatibility.
The actual implementation has been split into adapters/pravo/adapter/ subpackage.
"""

from adapters.pravo.adapter import PravoAdapter
from adapters.pravo.adapter.constants import (  # noqa: F401
    _CACHE_POPULATE_TTL,
    _INGEST_PAGE_SIZE,
    _SOURCE_URL,
    _STALE_CACHE_TTL,
    _STUB_DOCUMENTS,
    _STUB_PUBLISH_IDS_INITIAL,
    _STUB_PUBLISH_IDS_NEW,
    _build_stub_documents,
)

__all__ = [
    "PravoAdapter",
]
