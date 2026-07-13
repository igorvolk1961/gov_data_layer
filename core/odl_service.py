"""ODLService — единый core-класс, реализующий ODLServiceProtocol.

Принимает список SourceAdapter'ов (через DI) и делегирует им методы Protocol.
При поиске опрашивает все адаптеры и агрегирует результаты.
При получении конкретного документа определяет нужный адаптер по source_id.

Поддерживает опциональную персистентность в PostgreSQL через DatabaseClient
и репозитории. Если DatabaseClient не передан — работает без БД.
Если передан — персистентность обязательна, ошибки БД пробрасываются наверх.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.cache import CacheClient
from core.errors import NotFoundError
from core.models.models import (
    Citation,
    DocumentDetail,
    SearchContext,
    SearchResponse,
    SearchResult,
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

    Опционально принимает DatabaseClient для персистентности в PostgreSQL.
    Если DatabaseClient не передан — работает без БД.
    Если передан — персистентность обязательна, ошибки БД пробрасываются наверх.
    """

    def __init__(
        self,
        adapters: Sequence[SourceAdapter],
        tracer: Tracer | None = None,
        cache: CacheClient | None = None,
        db: DatabaseClient | None = None,
    ) -> None:
        self._adapters = list(adapters)
        self._tracer: Tracer | None = tracer
        self._cache: CacheClient | None = cache
        self._db: DatabaseClient | None = db
        self._doc_repo: DocumentRepository | None = None
        self._ref_repo: ReferenceRepository | None = None
        self._section_repo: SectionRepository | None = None
        self._change_repo: ChangeTrackingRepository | None = None

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

    async def _persist_document(
        self,
        doc: OfficialDocument,
        source_id: str,
        toc: list[TocNode] | None = None,
    ) -> None:
        """Persist a canonical document + its sections to PostgreSQL.

        If DatabaseClient is not configured (self._db is None), does nothing.
        If configured, persistence is mandatory — errors propagate to the caller.

        This is called as a side-effect from get_document_detail(), so the
        try/except in that method will catch and log any DB errors without
        failing the API response.
        """
        if self._db is None:
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
        """Поиск документов по всем адаптерам с агрегацией результатов."""
        with self.tracer.trace("search_documents", query=query) as span:
            span.set_input(
                {
                    "query": query,
                    "context": context.model_dump(mode="json") if context else None,
                }
            )
            all_results: list[SearchResult] = []
            for adapter in self._adapters:
                try:
                    results = await adapter.search(query, context)
                    all_results.extend(results)
                except Exception:
                    logger.exception(
                        "Adapter %s failed during search — skipping",
                        adapter.source_id,
                    )
            response = SearchResponse(
                results=all_results,
                total_count=len(all_results),
                offset=context.offset if context else 0,
            )
            span.set_output({"total_count": response.total_count, "offset": response.offset})
            return response

    async def get_document_detail(
        self,
        source_id: str,
    ) -> DocumentDetail:
        """Полная карточка документа — делегирует адаптеру по source_id.

        После получения документа от адаптера, опционально сохраняет его
        в PostgreSQL (если DatabaseClient передан в конструктор).
        Ошибки БД пробрасываются наверх и обрабатываются вызывающим кодом.
        """
        with self.tracer.trace("get_document_detail", source_id=source_id) as span:
            span.set_input({"source_id": source_id})
            adapter = self._get_adapter(source_id)
            doc = await adapter.get(source_id)
            try:
                toc = await adapter.get_toc(document_id=doc.id)
            except NotFoundError:
                # Document exists but TOC not found — return empty TOC
                # rather than failing the entire document detail request.
                # This can happen if the adapter hasn't indexed the TOC yet.
                logger.warning(
                    "TOC not found for document %s (source_id=%s) — returning empty TOC",
                    doc.id,
                    source_id,
                )
                toc = []

            detail = DocumentDetail(
                id=doc.id,
                title=doc.title,
                url=doc.url,
                source_name=doc.source.name,
                jurisdiction=doc.jurisdiction,
                region=doc.region,
                topic=doc.topic,
                organization=doc.organization,
                ingest_date=doc.ingest_date,
                valid_from=doc.valid_from,
                valid_to=doc.valid_to,
                legal_status=doc.legal_status,
                citations=[
                    Citation(
                        text=doc.summary or doc.title,
                        source_id=doc.id,
                        url=doc.url,
                        section=[toc[0].title] if toc else None,
                    ),
                ],
                toc=toc,
            )
            span.set_output({"document_id": detail.id, "title": detail.title})

        # Persist to PostgreSQL outside the tracing span (side-effect, not core logic)
        await self._persist_document(doc, source_id, toc)

        return detail

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
