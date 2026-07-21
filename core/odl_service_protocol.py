"""ODLService Protocol — контракт для всех реализаций сервиса.

Определяет единый интерфейс бизнес-логики слоя.
MCP-сервер и REST-сервер работают через этот Protocol,
что позволяет подменять реализацию (заглушка → настоящий сервис)
без изменения транспортного слоя.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from core.models.models import (
    DocumentDetail,
    SearchContext,
    SearchResponse,
)


class ReferenceCounts(BaseModel):
    """Counts of records in reference tables for admin verification."""

    region: int = 0
    organization: int = 0
    document_type: int = 0
    topic: int = 0
    document: int = 0
    document_section: int = 0
    section_topic: int = 0


class QdrantCollectionInfo(BaseModel):
    """Information about a Qdrant collection for admin verification."""

    exists: bool = False
    count: int = 0


class AdminQdrantStatus(BaseModel):
    """Qdrant collections status for admin verification."""

    documents: QdrantCollectionInfo = Field(default_factory=QdrantCollectionInfo)
    topics: QdrantCollectionInfo = Field(default_factory=QdrantCollectionInfo)


class DocumentStatus(BaseModel):
    """Full status of a document across DB and Qdrant."""

    publish_id: str
    in_postgres: bool = False
    doc_uuid: str | None = None
    chunk_count: int = 0
    section_count: int = 0


@runtime_checkable
class ODLServiceProtocol(Protocol):
    """Протокол единого core-класса ODLService.

    Все методы асинхронные. Принимают модели из core.models.models
    и возвращают модели оттуда же.
    """

    async def search_documents(
        self,
        query: str,
        context: SearchContext | None = None,
        parent_span: Any = None,
    ) -> SearchResponse:
        """Поиск документов по запросу.

        Args:
            query: Свободный текст вопроса/интент пользователя.
            context: Опциональные параметры фильтрации (регион, тема и т.д.).
            parent_span: Родительский span для построения иерархии трейсов.

        Returns:
            SearchResponse с результатами поиска и мета-информацией для пагинации.

        Raises:
            InvalidInputError: Некорректный запрос.
        """
        ...

    async def get_document_detail(
        self,
        source_id: str,
        query: str | None = None,
        context: SearchContext | None = None,
        max_citation_length: int = 2000,
    ) -> DocumentDetail:
        """Получить полную карточку документа по ID.

        Args:
            source_id: Идентификатор документа в источнике
                (формат `{source_id}-{publish_id}`, как возвращает search).
            query: Опциональный поисковый запрос для фильтрации citations.
                Если передан — возвращаются только цитаты из разделов,
                релевантных запросу (векторный поиск по чанкам документа).
            context: Опциональные параметры фильтрации (регион, тема,
                score_threshold и т.д.) для поиска релевантных чанков.
                Игнорируется если query не передан.
            max_citation_length: Максимальная суммарная длина всех цитат
                в символах (default: 2000). Если общая длина превышает
                лимит — менее релевантные цитаты отбрасываются.

        Returns:
            DocumentDetail — полная карточка с текстом, цитатами и оглавлением.

        Raises:
            NotFoundError: Документ не найден.
            SourceUnavailableError: Источник временно недоступен.
        """
        ...

    # ── Admin / Verification Methods ──────────────────────────────────

    async def admin_get_reference_counts(self) -> ReferenceCounts:
        """Get counts of all reference tables for verification."""
        ...

    async def admin_get_qdrant_status(self) -> AdminQdrantStatus:
        """Get Qdrant collections status for verification."""
        ...


__all__ = [
    "AdminQdrantStatus",
    "DocumentStatus",
    "ODLServiceProtocol",
    "QdrantCollectionInfo",
    "ReferenceCounts",
]
