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
from typing import TYPE_CHECKING, Any

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
    chunker: DocStructSplitter,
    embedder: Embedder,
    qdrant: QdrantStore,
    section_repo: SectionRepository | None = None,
    section_uuids: dict[str, str] | None = None,
    region: str | None = None,
    region_id: str | None = None,
    parent_span: Any = None,
) -> tuple[list[DocumentChunk], list[TocNode]]:
    """Process document text: chunk -> persist sections -> embed -> link topics -> Qdrant.

    Uses DocStructSplitter.split_text() which parses the text ONCE
    and returns both chunks and TOC.

    After chunking, if ``section_repo`` is provided and the TOC is non-empty,
    sections are persisted to PostgreSQL. The returned external_id -> UUID
    mapping is then set on each chunk's ``section_uuids`` field, linking
    Qdrant points to their corresponding PostgreSQL section records.

    After embedding, if ``section_repo`` is available, chunks are linked to
    topics (rubrics) via link_chunks_to_topics() — each chunk searches the
    Qdrant 'topics' collection for semantically similar rubrics.

    All CPU-bound steps (chunking, embedding) run in thread pool executors.

    Args:
        text: Full document text (from OCR).
        document_id: External document ID (source_id-publish_id).
        doc_uuid: UUID of the document record in PostgreSQL.
        chunker: DocStructSplitter instance (required).
        embedder: Embedder instance (required).
        qdrant: QdrantStore instance (required).
        section_repo: Optional SectionRepository for persisting TOC sections.
        section_uuids: Optional pre-existing mapping of external_id -> UUID.
                       If provided, persistence is skipped.

    Returns:
        Tuple of (chunks, toc).
    """
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
        if not text:
            child = _child("pipeline.skip_empty")
            with child:
                pass  # empty text — skip
            return [], []

        # 1. Chunk + TOC
        child = _child("pipeline.chunk")
        with child:
            chunks, toc = await chunker.split_text(
                text, document_id, doc_uuid, section_uuids, parent_span=child
            )
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
                    # Error already recorded via child.set_error(exc) above

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

        # 5. Link chunks to topics (rubrics)
        if resolved_section_uuids and section_repo is not None:
            child = _child("pipeline.link_topics")
            with child:
                try:
                    from core.persistence.repository.section_topic_repo import (
                        SectionTopicRepository,
                    )

                    st_repo = SectionTopicRepository(section_repo._db)
                    links_count = await link_chunks_to_topics(
                        chunks,
                        embedder=embedder,
                        qdrant=qdrant,
                        section_topic_repo=st_repo,
                    )
                    child.set_output({"links_created": links_count})
                except Exception as exc:
                    child.set_error(exc)
                    child.set_output({"error": str(exc)[:200]})

        # 6. Store in Qdrant (WITH topic_ids already populated)
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


async def link_chunks_to_topics(
    chunks: list[DocumentChunk],
    embedder: Embedder,
    qdrant: QdrantStore,
    section_topic_repo: Any = None,
    max_topics_per_chunk: int = 3,
    score_threshold: float = 0.25,
) -> int:
    """Link chunks to semantically similar topics, then aggregate up to sections.

    For each chunk: embed chunk text -> search Qdrant 'topics' collection ->
    set chunk.topic_ids. Then aggregate per section: union of all chunk topic_ids
    -> save to section_topic table.

    Args:
        chunks: List of DocumentChunk from the pipeline.
        embedder: Embedder instance (required).
        qdrant: QdrantStore instance (required).
        section_topic_repo: SectionTopicRepository instance.
        max_topics_per_chunk: Max topics to link per chunk.
        score_threshold: Minimum similarity score.

    Returns:
        Total number of chunk-topic links created.
    """
    if not chunks or section_topic_repo is None:
        return 0

    total_links = 0
    # section_uuid -> set of topic_ids (aggregated from chunks)
    section_topics: dict[str, set[str]] = {}

    for chunk in chunks:
        if not chunk.text.strip():
            continue

        # 1. Embed chunk text
        emb = await embedder.embed([chunk.text])
        if not emb or not emb[0]:
            continue

        # 2. Search Qdrant topics by similarity to CHUNK text
        matches = await qdrant.search_topics(
            query_embedding=emb[0],
            limit=max_topics_per_chunk,
            score_threshold=score_threshold,
        )

        # 3. Set topic_ids and topic_scores directly on the chunk
        topic_ids = [m["topic_id"] for m in matches]
        topic_scores = {m["topic_id"]: m["score"] for m in matches}
        chunk.topic_ids = topic_ids
        chunk.topic_scores = topic_scores
        total_links += len(topic_ids)

        # 4. Aggregate: for each section this chunk belongs to,
        #    add its topic_ids to the section's set
        for sec_uuid in chunk.section_uuids:
            if sec_uuid:
                if sec_uuid not in section_topics:
                    section_topics[sec_uuid] = set()
                section_topics[sec_uuid].update(topic_ids)

    # 5. Persist section->topic aggregations to section_topic table
    if section_topics:
        links = []
        for sec_uuid, sec_topic_ids in section_topics.items():
            for tid in sec_topic_ids:
                links.append({"section_id": sec_uuid, "topic_id": tid, "score": 1.0})
        if links:
            await section_topic_repo.batch_link(links)

    return total_links


__all__ = [
    "link_chunks_to_topics",
    "process_document_text",
]
