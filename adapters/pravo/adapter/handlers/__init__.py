"""Abstract base handlers for PravoAdapter strategy pattern.

Each handler defines the interface for one SourceAdapter protocol method.
Production and stub implementations inherit from these bases.
"""

from __future__ import annotations

from adapters.pravo.adapter.handlers.get import BaseGetHandler
from adapters.pravo.adapter.handlers.get_content import BaseGetContentHandler
from adapters.pravo.adapter.handlers.ingest import BaseIngestHandler
from adapters.pravo.adapter.handlers.list_topics import BaseListTopicsHandler
from adapters.pravo.adapter.handlers.search import BaseSearchHandler

__all__ = [
    "BaseGetContentHandler",
    "BaseGetHandler",
    "BaseIngestHandler",
    "BaseListTopicsHandler",
    "BaseSearchHandler",
]
