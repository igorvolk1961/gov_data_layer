"""Ingest Pipeline — shared document processing pipeline.

Mode-independent pipeline: chunk -> persist sections -> embed -> store in Qdrant.
Uses DocStructSplitter.split_text() which does ONE parse and
returns both chunks and TOC.

After chunking, if a SectionRepository is available, the TOC sections
are persisted to PostgreSQL and the resulting external_id -> UUID mapping
is set on each chunk (DocumentChunk.section_uuids).

All CPU-bound operations (chunking via spaCy, embedding via transformers)
run in thread pool executors to avoid blocking the event loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.analyzer.section_analyzer import SectionFact
    from core.index.qdrant_store import QdrantStore
    from core.ingest.chunker import DocStructSplitter
    from core.ingest.embedder import Embedder
    from core.models.models import DocumentChunk, TocNode
    from core.persistence.repository.section_repo import SectionRepository


async def process_document_text(
    text: str,
    document_id: str,
    doc_uuid: str,
    chunker: DocStructSplitter | None = None,
    embedder: Embedder | None = None,
    qdrant: QdrantStore | None = None,
    section_repo: SectionRepository | None = None,
    section_uuids: dict[str, str] | None = None,
    region: str | None = None,
    region_id: str | None = None,
) -> tuple[list[DocumentChunk], list[TocNode]]:
    """Process document text: chunk -> persist sections -> embed -> Qdrant.

    Uses DocStructSplitter.split_text() which parses the text ONCE
    and returns both chunks and TOC.

    After chunking, if ``section_repo`` is provided and the TOC is non-empty,
    sections are persisted to PostgreSQL. The returned external_id -> UUID
    mapping is then set on each chunk's ``section_uuids`` field, linking
    Qdrant points to their corresponding PostgreSQL section records.

    All CPU-bound steps (chunking, embedding) run in thread pool executors.

    Args:
        text: Full document text (from OCR).
        document_id: External document ID (source_id-publish_id).
        doc_uuid: UUID of the document record in PostgreSQL.
        chunker: DocStructSplitter instance (lazy-init if None).
        embedder: Embedder instance (lazy-init if None).
        qdrant: QdrantStore instance (lazy-init if None).
        section_repo: Optional SectionRepository for persisting TOC sections.
        section_uuids: Optional pre-existing mapping of external_id -> UUID.
                       If provided, persistence is skipped.

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
            with tracer.trace("pipeline.skip_empty") if tracer else _null_context():
                pass  # empty text — skip
            return [], []

        # 1. Chunk + TOC (один парсинг!)
        with tracer.trace("pipeline.chunk") if tracer else _null_context():
            chunks, toc = await chunker.split_text(text, document_id, doc_uuid, section_uuids)
            if not chunks:
                span = _NullSpan() if tracer is None else tracer.trace("pipeline.no_chunks")
                with span:
                    span.set_input({"document_id": document_id})
                return [], toc
            # Propagate region metadata to each chunk
            if region is not None or region_id is not None:
                for chunk in chunks:
                    if region is not None:
                        chunk.region = region
                    if region_id is not None:
                        chunk.region_id = region_id

        # 2. Persist sections to PostgreSQL (if repo is available and not already persisted)
        resolved_section_uuids = section_uuids
        if resolved_section_uuids is None and section_repo is not None and toc and doc_uuid:
            span = _NullSpan() if tracer is None else tracer.trace("pipeline.persist_sections")
            with span:
                span.set_input({"doc_uuid": doc_uuid, "section_count": len(toc)})
                try:
                    resolved_section_uuids = await section_repo.upsert_sections(doc_uuid, toc)
                    span.set_output({"section_uuids_count": len(resolved_section_uuids)})
                    # Set section_uuids on each chunk using the mapping
                    for chunk in chunks:
                        chunk.section_uuids = [
                            resolved_section_uuids.get(eid, "")
                            for eid in chunk.section_external_ids
                        ]
                except Exception as exc:
                    span.set_error(exc)
                    span.set_output({"error": str(exc)[:200]})
                    # Non-fatal — chunks without section_uuids still work

        # 3. Semantic analysis + persistence of legal facts (stub, DB only)
        if resolved_section_uuids and doc_uuid and section_repo is not None:
            span = _NullSpan() if tracer is None else tracer.trace("pipeline.analyze_sections")
            with span:
                try:
                    from core.analyzer import SectionAnalyzer
                    from core.persistence.repository import ChangeTrackingRepository

                    analyzer = SectionAnalyzer()
                    ct_repo = ChangeTrackingRepository(section_repo._db)
                    all_facts: list[SectionFact] = []
                    for chunk in chunks:
                        sec_ext_id = (
                            chunk.section_external_ids[0] if chunk.section_external_ids else ""
                        )
                        facts = analyzer.analyze(chunk.text, sec_ext_id)
                        all_facts.extend(facts)
                    if all_facts:
                        await ct_repo.save_analysis_facts(
                            all_facts, doc_uuid, resolved_section_uuids
                        )
                        span.set_output({"facts_saved": len(all_facts)})
                        # Deactivate affected sections in Qdrant
                        if qdrant is not None:
                            from datetime import date as _date

                            affected_uuids: list[str] = []
                            effective_date: _date | None = None
                            for fact in all_facts:
                                if fact.target_document_id:
                                    # For REVOKE: get sections of target doc
                                    try:
                                        target_sections = await section_repo.get_sections(
                                            fact.target_document_id
                                        )
                                        for sec in target_sections:
                                            if sec.id in resolved_section_uuids:
                                                affected_uuids.append(
                                                    resolved_section_uuids[sec.id]
                                                )
                                    except Exception:
                                        pass
                                # Use current doc's valid_from as default effective_date
                                if effective_date is None and fact.effective_date:
                                    effective_date = fact.effective_date
                            if affected_uuids:
                                deactivated = await qdrant.deactivate_sections(
                                    affected_uuids,
                                    effective_date or _date.today(),
                                )
                                span.set_output({"deactivated_chunks": deactivated})
                except Exception as exc:
                    span.set_error(exc)
                    span.set_output({"error": str(exc)[:200]})

        # 5. Embed
        with tracer.trace("pipeline.embed") if tracer else _null_context():
            texts = [c.text for c in chunks]
            embeddings = await embedder.embed(texts)
            for chunk, emb in zip(chunks, embeddings, strict=True):
                chunk.embedding = emb

        # 6. Store in Qdrant
        with tracer.trace("pipeline.qdrant_upsert") if tracer else _null_context():
            await qdrant.upsert_chunks(chunks)

        return chunks, toc


class _NullSpan:
    """No-op span that accepts all tracer-like calls."""

    def set_input(self, *args: object, **kwargs: object) -> None:
        pass

    def set_output(self, *args: object, **kwargs: object) -> None:
        pass

    def set_error(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> _NullSpan:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _NullContext:
    """No-op context manager for when tracer is not available."""

    def __enter__(self) -> _NullSpan:
        return _NullSpan()

    def __exit__(self, *args: object) -> None:
        return None


def _null_context() -> _NullContext:
    return _NullContext()


__all__ = [
    "process_document_text",
]
