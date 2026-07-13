"""Module-level constants for PravoAdapter.

This module contains all configuration constants used by the adapter,
its handlers, and tests. Stub document data has been moved to the
stub/ subpackage handlers.
"""

from __future__ import annotations

# Base URL and document URL template for pravo.gov.ru
_SOURCE_URL = "http://publication.pravo.gov.ru"
_DOCUMENT_URL_TEMPLATE = f"{_SOURCE_URL}/document/{{publish_id}}"

# Stale cache TTL: how long a cached document is considered "fresh" (seconds)
_STALE_CACHE_TTL = 3600.0  # 1 hour

# Cache TTL for authority/doc_type lookups (seconds)
_CACHE_POPULATE_TTL = 3600.0  # 1 hour

# Default page size for ingest
_INGEST_PAGE_SIZE = 50


__all__ = [
    "_CACHE_POPULATE_TTL",
    "_DOCUMENT_URL_TEMPLATE",
    "_INGEST_PAGE_SIZE",
    "_SOURCE_URL",
    "_STALE_CACHE_TTL",
]
