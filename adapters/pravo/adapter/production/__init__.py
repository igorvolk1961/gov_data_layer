"""Production implementations of PravoAdapter handlers.

Each module implements one SourceAdapter protocol method using
the real pravo.gov.ru API.
"""

from __future__ import annotations

from adapters.pravo.adapter.production.get import ProductionGetHandler
from adapters.pravo.adapter.production.get_content import ProductionGetContentHandler
from adapters.pravo.adapter.production.ingest import ProductionIngestHandler
from adapters.pravo.adapter.production.list_topics import ProductionListTopicsHandler
from adapters.pravo.adapter.production.search import ProductionSearchHandler

__all__ = [
    "ProductionGetContentHandler",
    "ProductionGetHandler",
    "ProductionIngestHandler",
    "ProductionListTopicsHandler",
    "ProductionSearchHandler",
]
