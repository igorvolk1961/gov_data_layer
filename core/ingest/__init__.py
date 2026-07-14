"""Ingest — document ingestion pipeline.

Components:
- DocStructSplitter: structural chunking for Russian official documents
- Embedder: text embedding using sentence-transformers
"""

from __future__ import annotations

from core.ingest.chunker import DocStructSplitter
from core.ingest.embedder import Embedder

__all__ = [
    "DocStructSplitter",
    "Embedder",
]
