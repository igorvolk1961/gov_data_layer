"""ODLService — единый core-класс, реализующий ODLServiceProtocol.

Делегирует все методы SourceAdapter'у (через DI).
На данный момент (Phase 4) используется StubAdapter.
Phase 4.5 заменит заглушки на реальную бизнес-логику.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.errors import NotFoundError
from core.models.models import (
    Citation,
    DocumentDetail,
    SearchContext,
    SearchResponse,
    TocNode,
    TopicNode,
)
from core.observability import get_logger, get_tracer
from core.observability.tracer import Tracer
from core.odl_service_protocol import ODLServiceProtocol

if TYPE_CHECKING:
    from adapters.base import SourceAdapter

logger = get_logger(__name__)


class ODLService(ODLServiceProtocol):
    """Единый core-класс ODLService.

    Принимает SourceAdapter (через DI) и делегирует ему все 4 метода Protocol.
    """

    def __init__(
        self,
        adapter: SourceAdapter,
        tracer: Tracer | None = None,
    ) -> None:
        self._adapter = adapter
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

    async def search_documents(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> SearchResponse:
        """Поиск документов через StubAdapter."""
        with self.tracer.trace("search_documents", query=query) as span:
            span.set_input(
                {
                    "query": query,
                    "context": context.model_dump(mode="json") if context else None,
                }
            )
            results = await self._adapter.search(query, context)
            response = SearchResponse(
                results=results,
                total_count=len(results),
                offset=context.offset if context else 0,
            )
            span.set_output({"total_count": response.total_count, "offset": response.offset})
            return response

    async def get_document_detail(
        self,
        source_id: str,
    ) -> DocumentDetail:
        """Полная карточка документа — делегирует адаптеру."""
        with self.tracer.trace("get_document_detail", source_id=source_id) as span:
            span.set_input({"source_id": source_id})
            doc = await self._adapter.get(source_id)
            try:
                toc = await self._adapter.get_toc(document_id=doc.id)
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
            try:
                content = await self._adapter.get_content(document_id=doc.id)
            except NotFoundError:
                logger.warning(
                    "Content not found for document %s (source_id=%s) — returning empty content",
                    doc.id,
                    source_id,
                )
                content = ""
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
                content=content,
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
        """Просмотр рубрикатора — делегирует адаптеру."""
        with self.tracer.trace("list_topics", parent_id=str(parent_id)) as span:
            span.set_input({"parent_id": parent_id, "query": query})
            result = await self._adapter.list_topics(parent_id=parent_id, query=query)
            span.set_output({"count": len(result)})
            return result

    async def get_toc(
        self,
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> list[TocNode]:
        """Оглавление документа — делегирует адаптеру."""
        with self.tracer.trace("get_toc", document_id=document_id) as span:
            span.set_input(
                {
                    "document_id": document_id,
                    "parent_section_id": parent_section_id,
                    "query": query,
                }
            )
            result = await self._adapter.get_toc(
                document_id=document_id,
                parent_section_id=parent_section_id,
                query=query,
            )
            span.set_output({"count": len(result)})
            return result


__all__ = [
    "ODLService",
]
