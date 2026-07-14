"""Ingest Pipeline — shared document processing pipeline.

Mode-independent pipeline: chunk -> embed -> store in Qdrant.
Uses DocStructSplitter.split_text() which does ONE parse and
returns both chunks and TOC.

All CPU-bound operations (chunking via spaCy, embedding via transformers)
run in thread pool executors to avoid blocking the event loop.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.index.qdrant_store import QdrantStore
    from core.ingest.chunker import DocStructSplitter
    from core.ingest.embedder import Embedder
    from core.models.models import DocumentChunk, TocNode

logger = logging.getLogger(__name__)


async def process_document_text(
    text: str,
    document_id: str,
    doc_uuid: str,
    chunker: DocStructSplitter | None = None,
    embedder: Embedder | None = None,
    qdrant: QdrantStore | None = None,
    section_uuids: dict[str, str] | None = None,
) -> tuple[list[DocumentChunk], list[TocNode]]:
    """Process document text: chunk -> embed -> Qdrant. Returns chunks and TOC.

    Uses DocStructSplitter.split_text() which parses the text ONCE
    and returns both chunks and TOC.

    All CPU-bound steps (chunking, embedding) run in thread pool executors.

    Args:
        text: Full document text (from OCR).
        document_id: External document ID (source_id-publish_id).
        doc_uuid: UUID of the document record in PostgreSQL.
        chunker: DocStructSplitter instance (lazy-init if None).
        embedder: Embedder instance (lazy-init if None).
        qdrant: QdrantStore instance (lazy-init if None).
        section_uuids: Optional mapping of external_id -> UUID for sections.

    Returns:
        Tuple of (chunks, toc).
    """
    from core.index.qdrant_store import QdrantStore as _QdrantStore
    from core.ingest.chunker import DocStructSplitter as _Chunker
    from core.ingest.embedder import Embedder as _Embedder

    # Tracing
    try:
        from core.observability import get_tracer

        tracer = get_tracer()
    except Exception:
        tracer = None

    with tracer.trace("pipeline.process_document_text") if tracer else _null_context():
        chunker = chunker or _Chunker()
        embedder = embedder or _Embedder()
        qdrant = qdrant or _QdrantStore()

        if not text:
            logger.warning("Empty text for document '%s' — skipping pipeline", document_id)
            return [], []

        # 1. Chunk + TOC (один парсинг!)
        with tracer.trace("pipeline.chunk") if tracer else _null_context():
            chunks, toc = await chunker.split_text(text, document_id, doc_uuid, section_uuids)
            if not chunks:
                logger.warning("No chunks produced for document '%s'", document_id)
                return [], toc

        logger.info(
            "Produced %d chunks and %d TOC entries for document '%s'",
            len(chunks),
            len(toc),
            document_id,
        )

        # 2. Embed
        with tracer.trace("pipeline.embed") if tracer else _null_context():
            texts = [c.text for c in chunks]
            embeddings = await embedder.embed(texts)
            for chunk, emb in zip(chunks, embeddings, strict=True):
                chunk.embedding = emb

        # 3. Store in Qdrant
        with tracer.trace("pipeline.qdrant_upsert") if tracer else _null_context():
            await qdrant.upsert_chunks(chunks)

        return chunks, toc


class _NullContext:
    """No-op context manager for when tracer is not available."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None


def _null_context() -> _NullContext:
    return _NullContext()


__all__ = [
    "process_document_text",
]
