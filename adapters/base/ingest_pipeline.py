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

import contextlib
import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

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
    parent_span: Any = None,
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

    # Tracing — create ONE parent span for the entire pipeline
    try:
        from core.observability import get_tracer

        tracer = get_tracer()
    except Exception:
        tracer = None

    # When parent_span is provided, we reuse it as the parent for child spans
    # but do NOT enter its context manager again (it's already active in caller).
    # When parent_span is None, create a new root span for this pipeline call.
    if parent_span is not None:
        pipeline_span = parent_span
    else:
        pipeline_span = tracer.trace("pipeline.process_document_text") if tracer else _NullSpan()

    # Define a helper so child spans are clean
    def _child(name: str) -> Any:
        return tracer.span(name, parent=pipeline_span) if tracer else _NullSpan()

    ctx = pipeline_span if parent_span is None else contextlib.nullcontext()

    with ctx:
        chunker = chunker or _Chunker()
        embedder = embedder or _Embedder()
        qdrant = qdrant or _QdrantStore()

        if not text:
            child = _child("pipeline.skip_empty")
            with child:
                pass  # empty text — skip
            return [], []

        # 1. Chunk + TOC
        child = _child("pipeline.chunk")
        with child:
            chunks, toc = await chunker.split_text(text, document_id, doc_uuid, section_uuids)
            if not chunks:
                child = _child("pipeline.no_chunks")
                with child:
                    child.set_input({"document_id": document_id})
                return [], toc
            if region is not None or region_id is not None:
                for chunk in chunks:
                    if region is not None:
                        chunk.region = region
                    if region_id is not None:
                        chunk.region_id = region_id

        # 2. Persist sections to PostgreSQL
        resolved_section_uuids = section_uuids
        if resolved_section_uuids is None and section_repo is not None and toc and doc_uuid:
            child = _child("pipeline.persist_sections")
            with child:
                child.set_input({"doc_uuid": doc_uuid, "section_count": len(toc)})
                try:
                    resolved_section_uuids = await section_repo.upsert_sections(doc_uuid, toc)
                    child.set_output({"section_uuids_count": len(resolved_section_uuids)})
                    for chunk in chunks:
                        chunk.section_uuids = [
                            resolved_section_uuids.get(eid, "")
                            for eid in chunk.section_external_ids
                        ]
                except Exception as exc:
                    child.set_error(exc)
                    child.set_output({"error": str(exc)[:200]})
                    import traceback as _tb

                    logger.error(
                        "Section persistence failed for doc %s: %s\n%s",
                        doc_uuid,
                        exc,
                        _tb.format_exc(),
                    )

        # 3. Semantic analysis + persistence of legal facts
        if resolved_section_uuids and doc_uuid and section_repo is not None:
            child = _child("pipeline.analyze_sections")
            with child:
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
                        child.set_output({"facts_saved": len(all_facts)})
                        if qdrant is not None:
                            from datetime import date as _date

                            affected_uuids: list[str] = []
                            effective_date: _date | None = None
                            for fact in all_facts:
                                if fact.target_document_id:
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
                                if effective_date is None and fact.effective_date:
                                    effective_date = fact.effective_date
                            if affected_uuids:
                                deactivated = await qdrant.deactivate_sections(
                                    affected_uuids,
                                    effective_date or _date.today(),
                                )
                                child.set_output({"deactivated_chunks": deactivated})
                except Exception as exc:
                    child.set_error(exc)
                    child.set_output({"error": str(exc)[:200]})

        # 4. Embed
        child = _child("pipeline.embed")
        with child:
            texts = [c.text for c in chunks]
            embeddings = await embedder.embed(texts)
            for chunk, emb in zip(chunks, embeddings, strict=True):
                chunk.embedding = emb

        # 5. Store in Qdrant
        child = _child("pipeline.qdrant_upsert")
        with child:
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


async def link_sections_to_topics(
    chunks: list[DocumentChunk],
    embedder: Embedder | None = None,
    qdrant: QdrantStore | None = None,
    section_topic_repo: Any = None,
    max_topics_per_section: int = 3,
    score_threshold: float = 0.25,
    parent_span: Any = None,
) -> int:
    """Link document sections to semantically similar topics (rubrics).

    For each section with a UUID, embed its text, query Qdrant ``topics``
    collection, and insert matching topics into the ``section_topic`` table.

    Args:
        chunks: List of DocumentChunk from the pipeline.
        embedder: Embedder instance (lazy-init if None).
        qdrant: QdrantStore instance (lazy-init if None).
        section_topic_repo: SectionTopicRepository instance.
        max_topics_per_section: Max topics to link per section.
        score_threshold: Minimum similarity score.

    Returns:
        Total number of section-topic links created.
    """
    if not chunks or section_topic_repo is None:
        return 0

    # Lazy init (same pattern as process_document_text)
    if embedder is None:
        from core.ingest.embedder import Embedder as _Embedder
        embedder = _Embedder()
    if qdrant is None:
        from core.index.qdrant_store import QdrantStore as _QdrantStore
        qdrant = _QdrantStore()

    # Build a map: section_uuid -> concatenated text from all chunks sharing that section
    section_texts: dict[str, list[str]] = {}
    for chunk in chunks:
        for sec_uuid in chunk.section_uuids:
            if sec_uuid:
                section_texts.setdefault(sec_uuid, []).append(chunk.text)

    if not section_texts:
        return 0

    # Get tracer
    _link_tracer: Any = None
    try:
        from core.observability import get_tracer as _gt

        _link_tracer = _gt()
    except Exception:
        _link_tracer = None

    def _link_child(name: str) -> Any:
        if _link_tracer is not None and hasattr(_link_tracer, "span"):
            return _link_tracer.span(name, parent=parent_span)
        return _NullSpan()

    total_links = 0

    for sec_uuid, texts in section_texts.items():
        full_text = " ".join(texts)[:2000]  # limit to 2000 chars
        if not full_text.strip():
            continue

        child = _link_child("pipeline.link_topics")
        with child:
            child.set_input({"section_uuid": sec_uuid[:8], "text_len": len(full_text)})
            try:
                # 1. Embed section text
                emb = await embedder.embed([full_text])
                if not emb or not emb[0]:
                    continue

                # 2. Search Qdrant topics by similarity
                matches = await qdrant.search_topics(
                    query_embedding=emb[0],
                    limit=max_topics_per_section,
                    score_threshold=score_threshold,
                )

                # 3. Link to topics via SectionTopicRepository
                # Use topic_id (DB UUID from Qdrant payload), NOT topic_uuid (Qdrant point ID)
                links = [
                    {"section_id": sec_uuid, "topic_id": m["topic_id"], "score": m["score"]}
                    for m in matches
                ]
                if links:
                    await section_topic_repo.batch_link(links)
                    total_links += len(links)
                    child.set_output(
                        {"links_created": len(links), "topics": [m["name"] for m in matches]}
                    )
            except Exception as exc:
                child.set_error(exc)
                child.set_output({"error": str(exc)[:200]})

    return total_links


__all__ = [
    "link_sections_to_topics",
    "process_document_text",
]
