"""ODLService — единый core-класс, реализующий ODLServiceProtocol.

Принимает список SourceAdapter'ов (через DI) и делегирует им методы Protocol.
При поиске опрашивает все адаптеры и агрегирует результаты.
При получении конкретного документа определяет нужный адаптер по source_id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from adapters.base import SourceAdapter

logger = get_logger(__name__)


class ODLService(ODLServiceProtocol):
    """Единый core-класс ODLService.

    Принимает список SourceAdapter'ов (через DI) и делегирует им методы Protocol.
    При поиске опрашивает все адаптеры и агрегирует результаты.
    """

    def __init__(
        self,
        adapters: Sequence[SourceAdapter],
        tracer: Tracer | None = None,
    ) -> None:
        self._adapters = list(adapters)
        self._tracer: Tracer | None = tracer

    @property
    def tracer(self) -> Tracer:
        """Lazy tracer — defers get_tracer() until first use.

        This avoids RuntimeError at import time when the tracer hasn't been
        configured yet (e.g. during test collection).
        """
        if self._tracer is None:
            self._tracer = get_tracer()
        return self._tracer

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
        """Полная карточка документа — делегирует адаптеру по source_id."""
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
