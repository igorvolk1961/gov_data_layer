"""ODLService — единый core-класс, реализующий ODLServiceProtocol.

Принимает список SourceAdapter'ов (через DI) и делегирует им методы Protocol.
При поиске опрашивает все адаптеры и агрегирует результаты.
При получении конкретного документа определяет нужный адаптер по source_id.

Поддерживает персистентность в PostgreSQL через DatabaseClient и репозитории.
Если DatabaseClient передан — персистентность обязательна, ошибки БД
пробрасываются наверх. Если не передан — персистентность не происходит,
логируется предупреждение.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.cache import CacheClient
from core.errors import NotFoundError
from core.index.qdrant_store import QdrantStore
from core.ingest.embedder import Embedder
from core.models.models import (
    Citation,
    ConfidenceSignals,
    DocumentChunk,
    DocumentDetail,
    LegalStatus,
    SearchContext,
    SearchResponse,
    SearchResult,
    SourceAvailability,
    TocNode,
    TopicNode,
)
from core.observability import get_logger, get_tracer
from core.observability.tracer import Tracer
from core.odl_service_protocol import ODLServiceProtocol
from core.persistence import DatabaseClient
from core.persistence.repository import (
    ChangeTrackingRepository,
    DocumentRepository,
    ReferenceRepository,
    SectionRepository,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from adapters.base import SourceAdapter
    from core.models.models import OfficialDocument

logger = get_logger(__name__)


class ODLService(ODLServiceProtocol):
    """Единый core-класс ODLService.

    Принимает список SourceAdapter'ов (через DI) и делегирует им методы Protocol.
    При поиске опрашивает все адаптеры и агрегирует результаты.

    Принимает DatabaseClient для персистентности в PostgreSQL.
    Если передан — персистентность обязательна, ошибки БД пробрасываются наверх.
    Если не передан — персистентность не происходит, логируется предупреждение.
    """

    def __init__(
        self,
        adapters: Sequence[SourceAdapter],
        tracer: Tracer | None = None,
        cache: CacheClient | None = None,
        db: DatabaseClient | None = None,
        qdrant: QdrantStore | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._adapters = list(adapters)
        self._tracer: Tracer | None = tracer
        self._cache: CacheClient | None = cache
        self._db: DatabaseClient | None = db
        self._qdrant: QdrantStore | None = qdrant
        self._embedder: Embedder | None = embedder
        self._doc_repo: DocumentRepository | None = None
        self._ref_repo: ReferenceRepository | None = None
        self._section_repo: SectionRepository | None = None
        self._change_repo: ChangeTrackingRepository | None = None

        # Pass DatabaseClient to adapters that support it
        if db is not None:
            for adapter in self._adapters:
                if hasattr(adapter, "_db"):
                    adapter._db = db

    @property
    def tracer(self) -> Tracer:
        """Lazy tracer — defers get_tracer() until first use.

        This avoids RuntimeError at import time when the tracer hasn't been
        configured yet (e.g. during test collection).
        """
        if self._tracer is None:
            self._tracer = get_tracer()
        return self._tracer

    @property
    def _doc_repo_lazy(self) -> DocumentRepository | None:
        """Lazy init of DocumentRepository (only if DB is available)."""
        if self._doc_repo is None and self._db is not None:
            ref_repo = self._ref_repo_lazy
            assert ref_repo is not None
            self._doc_repo = DocumentRepository(self._db, ref_repo)
        return self._doc_repo

    @property
    def _ref_repo_lazy(self) -> ReferenceRepository | None:
        """Lazy init of ReferenceRepository (only if DB is available)."""
        if self._ref_repo is None and self._db is not None:
            self._ref_repo = ReferenceRepository(self._db)
        return self._ref_repo

    @property
    def _section_repo_lazy(self) -> SectionRepository | None:
        """Lazy init of SectionRepository (only if DB is available)."""
        if self._section_repo is None and self._db is not None:
            self._section_repo = SectionRepository(self._db)
        return self._section_repo

    @property
    def _change_repo_lazy(self) -> ChangeTrackingRepository | None:
        """Lazy init of ChangeTrackingRepository (only if DB is available)."""
        if self._change_repo is None and self._db is not None:
            self._change_repo = ChangeTrackingRepository(self._db)
        return self._change_repo

    @property
    def _embedder_lazy(self) -> Embedder:
        """Lazy init of Embedder."""
        if self._embedder is None:
            self._embedder = Embedder()
        return self._embedder

    @property
    def _qdrant_lazy(self) -> QdrantStore | None:
        """Lazy access to QdrantStore."""
        return self._qdrant

    async def _persist_document(
        self,
        doc: OfficialDocument,
        source_id: str,
        toc: list[TocNode] | None = None,
    ) -> None:
        """Persist a canonical document + its sections to PostgreSQL.

        If DatabaseClient is not configured (self._db is None), logs a warning
        and returns. If configured, persistence is mandatory — errors propagate
        to the caller.

        This is called as a side-effect from get_document_detail(), so the
        try/except in that method will catch and log any DB errors without
        failing the API response.
        """
        if self._db is None:
            logger.warning(
                "Database not configured — skipping persistence for document %s (source=%s)",
                doc.id,
                source_id,
            )
            return

        # Ensure DB connection is established
        await self._db.connect()

        ref_repo = self._ref_repo_lazy
        doc_repo = self._doc_repo_lazy
        section_repo = self._section_repo_lazy

        # Narrow types: all repos are guaranteed non-None when _db is not None
        assert ref_repo is not None
        assert doc_repo is not None
        assert section_repo is not None

        # 1. Get or create data source
        source_uuid = await ref_repo.get_or_create_data_source(
            source_id=source_id,
            name=doc.source.name,
            url=doc.url,
        )

        # 2. Upsert the document
        doc_uuid = await doc_repo.upsert_document(doc, source_uuid)

        # 3. Upsert sections (TOC)
        if toc:
            await section_repo.upsert_sections(doc_uuid, toc)

    def _get_adapter(self, source_id: str) -> SourceAdapter:
        """Find the adapter that owns the given source_id.

        Matches by prefix: if source_id starts with adapter.source_id + '-',
        or equals adapter.source_id, that adapter is selected.
        Falls back to the first adapter if no match is found.
        """
        for adapter in self._adapters:
            if source_id == adapter.source_id or source_id.startswith(f"{adapter.source_id}-"):
                return adapter
        # Fallback to first adapter
        return self._adapters[0]

    async def search_documents(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> SearchResponse:
        """Поиск документов через Qdrant с обогащением из PostgreSQL.

        Векторный поиск по Qdrant → обогащение метаданных документа
        (url, source_name, title) из реляционной БД.
        Если БД недоступна — возвращаются только данные из Qdrant.
        """
        ctx = context or SearchContext()
        offset = ctx.offset
        max_results = ctx.max_results
        results: list[SearchResult] = []

        with self.tracer.trace("search_documents", query=query[:100]) as span:
            span.set_input(ctx.model_dump(mode="json"))

            if self._qdrant is None:
                span.set_output({"total_count": 0, "reason": "qdrant_not_configured"})
                return SearchResponse(results=[], total_count=0, offset=offset)

            try:
                embedder = self._embedder_lazy
                query_vector = await embedder.embed_query(query)
                filters = await self._qdrant.build_filter()

                with self.tracer.trace("search.qdrant") as qspan:
                    qdrant_chunks = await self._qdrant.search(
                        query_embedding=query_vector,
                        filters=filters,
                        limit=max_results + offset,
                    )
                    qspan.set_output({"hits": len(qdrant_chunks)})

                page_chunks = qdrant_chunks[offset : offset + max_results]

                # Обогащение из PostgreSQL
                doc_repo = self._doc_repo_lazy

                for chunk, score in page_chunks:
                    url = ""
                    source_name = ""
                    doc_title = chunk.text[:120] + ("…" if len(chunk.text) > 120 else "")

                    if doc_repo is not None:
                        with self.tracer.trace("search.pg_lookup") as pspan:
                            try:
                                doc_meta = await doc_repo.get_document_by_id(chunk.document_id)
                                if doc_meta is not None:
                                    url = doc_meta.url or ""
                                    source_name = doc_meta.source.name if doc_meta.source else ""
                                    doc_title = doc_meta.title or doc_title
                                    pspan.set_output({"found": True})
                                else:
                                    pspan.set_output({"found": False})
                            except Exception:
                                pspan.set_output({"found": False})

                    result = SearchResult(
                        id=chunk.document_id,
                        title=doc_title,
                        snippet=chunk.text[:300] + ("…" if len(chunk.text) > 300 else ""),
                        url=url,
                        source_name=source_name,
                        created_at=datetime.now(timezone.utc),
                        legal_status=LegalStatus.UNKNOWN,
                        confidence=ConfidenceSignals(
                            retrieval_relevance=score,
                            data_freshness=chunk.data_freshness,
                            source_availability=SourceAvailability.AVAILABLE,
                        ),
                    )
                    results.append(result)

            except Exception as exc:
                with self.tracer.trace("search.qdrant_error") as espan:
                    espan.set_error(exc)
                    espan.set_output({"error": str(exc)[:200]})

            response = SearchResponse(
                results=results,
                total_count=len(results),
                offset=offset,
            )
            span.set_output({"total_count": response.total_count})
            return response

    async def get_document_detail(
        self,
        source_id: str,
    ) -> DocumentDetail:
        """Полная карточка документа — делегирует адаптеру по source_id.

        После получения документа от адаптера:
        1. Пытается найти чанки документа в Qdrant (через document_id).
        2. Группирует чанки по section_path, объединяет тексты с учётом
           перекрытия, создаёт по одной Citation на раздел.
        3. Если Qdrant недоступен или чанков нет — текущее поведение
           (Citation из summary/title).

        Затем сохраняет документ в PostgreSQL (если DatabaseClient передан).
        Ошибка БД не ломает ответ — данные возвращаются агенту.
        """
        with self.tracer.trace("get_document_detail", source_id=source_id) as span:
            span.set_input({"source_id": source_id})
            adapter = self._get_adapter(source_id)
            doc = await adapter.get(source_id)
            try:
                toc = await adapter.get_toc(document_id=doc.id)
            except NotFoundError:
                with self.tracer.trace("detail.toc_not_found") as toc_span:
                    toc_span.set_input({"document_id": doc.id, "source_id": source_id})
                toc = []

            # Build citations from Qdrant chunks (if available)
            citations = await self._build_citations_from_qdrant(doc, toc)

            detail = DocumentDetail(
                id=doc.id,
                title=doc.title,
                url=doc.url,
                source_name=doc.source.name,
                jurisdiction=doc.jurisdiction,
                region=doc.region,
                topic=doc.topic,
                organization=[doc.organization] if doc.organization else [],
                created_at=doc.created_at,
                valid_from=doc.valid_from,
                valid_to=doc.valid_to,
                legal_status=doc.legal_status,
                citations=citations,
                toc=toc,
            )
            span.set_output({"document_id": detail.id, "title": detail.title})

        # Persist to PostgreSQL outside the tracing span (side-effect, not core logic)
        # Graceful degradation: ошибка БД не ломает ответ агента
        try:
            await self._persist_document(doc, source_id, toc)
        except Exception as exc:
            with self.tracer.trace("persistence.failed") as span:
                span.set_input(
                    {
                        "document_id": doc.id,
                        "source_id": source_id,
                    }
                )
                span.set_error(exc)

        return detail

    async def _build_citations_from_qdrant(
        self,
        doc: OfficialDocument,
        toc: list[TocNode],
    ) -> list[Citation]:
        """Build citations from Qdrant chunks, falling back to summary if unavailable.

        Groups chunks by section_path, merges with overlap handling,
        creates one Citation per section.
        """
        qdrant = self._qdrant_lazy
        if qdrant is not None:
            try:
                chunks = await qdrant.get_chunks_by_document_id(doc.id)
                if chunks:
                    return self._merge_chunks_to_citations(chunks, doc)
            except Exception as exc:
                with self.tracer.trace("detail.qdrant_error") as span:
                    span.set_input({"document_id": doc.id})
                    span.set_error(exc)

        # Fallback: one citation from summary / title
        return [
            Citation(
                text=doc.summary or doc.title,
                source_id=doc.id,
                url=doc.url,
                section=[toc[0].title] if toc else None,
            ),
        ]

    @staticmethod
    def _merge_chunks_to_citations(
        chunks: list[DocumentChunk],
        doc: OfficialDocument,
    ) -> list[Citation]:
        """Merge chunks grouped by section_path into one Citation per section.

        Chunks are already sorted by (section_path, section_chunk_index)
        from QdrantStore.get_chunks_by_document_id.

        Overlap handling: for consecutive chunks in the same section,
        detects suffix/prefix overlap and trims the duplicate portion
        before concatenation.
        """
        citations: list[Citation] = []

        # Group by section_path (preserving original order)
        grouped: dict[str, list[DocumentChunk]] = {}
        group_order: list[str] = []
        for chunk in chunks:
            key = "|".join(chunk.section_path)
            if key not in grouped:
                grouped[key] = []
                group_order.append(key)
            grouped[key].append(chunk)

        for key in group_order:
            group = grouped[key]
            merged = ODLService._merge_overlapping_chunks(group)
            section = group[0].section_path if group[0].section_path else None

            citations.append(
                Citation(
                    text=merged,
                    source_id=doc.id,
                    url=doc.url,
                    section=section,
                )
            )

        return citations

    @staticmethod
    def _merge_overlapping_chunks(chunks: list[DocumentChunk]) -> str:
        """Merge chunk texts with overlap trimming.

        Chunks are ordered by section_chunk_index (ascending).
        For each consecutive pair, if the end of the previous chunk
        overlaps with the start of the next chunk (≥50 chars match),
        the overlapping portion is removed from the next chunk.

        If no overlap is detected, chunks are joined with a space.
        """
        if not chunks:
            return ""
        if len(chunks) == 1:
            return chunks[0].text

        result = chunks[0].text
        for i in range(1, len(chunks)):
            prev = result
            curr = chunks[i].text

            # Find maximum overlap between end of prev and start of curr
            overlap_len = 0
            min_overlap = 50  # minimum chars to consider as intentional overlap
            max_check = min(len(prev), len(curr), 500)  # don't check beyond 500 chars

            for n in range(max_check, min_overlap - 1, -1):
                if prev[-n:] == curr[:n]:
                    overlap_len = n
                    break

            if overlap_len >= min_overlap:
                result = prev + curr[overlap_len:]
            else:
                # No significant overlap — join with separator
                result = prev + ("\n\n" if prev and curr else "") + curr

        return result

    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """Просмотр рубрикатора — делегирует первому адаптеру."""
        with self.tracer.trace("list_topics", parent_id=str(parent_id)) as span:
            span.set_input({"parent_id": parent_id, "query": query})
            all_topics: list[TopicNode] = []
            for adapter in self._adapters:
                try:
                    topics = await adapter.list_topics(parent_id=parent_id, query=query)
                    all_topics.extend(topics)
                except Exception:
                    logger.exception(
                        "Adapter %s failed during list_topics — skipping",
                        adapter.source_id,
                    )
            span.set_output({"count": len(all_topics)})
            return all_topics

    async def get_toc(
        self,
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> list[TocNode]:
        """Оглавление документа — делегирует адаптеру по source_id."""
        with self.tracer.trace("get_toc", document_id=document_id) as span:
            span.set_input(
                {
                    "document_id": document_id,
                    "parent_section_id": parent_section_id,
                    "query": query,
                }
            )
            adapter = self._get_adapter(document_id)
            result = await adapter.get_toc(
                document_id=document_id,
                parent_section_id=parent_section_id,
                query=query,
            )
            span.set_output({"count": len(result)})
            return result


__all__ = [
    "ODLService",
]
