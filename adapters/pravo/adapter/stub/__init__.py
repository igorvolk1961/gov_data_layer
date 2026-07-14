"""Stub implementations of PravoAdapter handlers.

Each module implements one SourceAdapter protocol method using
fixed stub data. This entire package can be deleted when stub
mode is no longer needed.
"""

from __future__ import annotations

from adapters.pravo.adapter.stub.get import StubGetHandler
from adapters.pravo.adapter.stub.get_content import StubGetContentHandler
from adapters.pravo.adapter.stub.ingest import StubIngestHandler
from adapters.pravo.adapter.stub.list_topics import StubListTopicsHandler
from adapters.pravo.adapter.stub.search import StubSearchHandler

__all__ = [
    "StubGetContentHandler",
    "StubGetHandler",
    "StubIngestHandler",
    "StubListTopicsHandler",
    "StubSearchHandler",
]
