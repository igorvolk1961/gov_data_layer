"""ODLService Protocol — контракт для всех реализаций сервиса.

Определяет единый интерфейс бизнес-логики слоя.
MCP-сервер и REST-сервер работают через этот Protocol,
что позволяет подменять реализацию (заглушка → настоящий сервис)
без изменения транспортного слоя.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from core.models.models import (
    DocumentDetail,
    SearchContext,
    SearchResponse,
    TocNode,
    TopicNode,
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
    ) -> SearchResponse:
        """Поиск документов по запросу.

        Args:
            query: Свободный текст вопроса/интент пользователя.
            context: Опциональные параметры фильтрации (регион, тема и т.д.).

        Returns:
            SearchResponse с результатами поиска и мета-информацией для пагинации.

        Raises:
            InvalidInputError: Некорректный запрос.
        """
        ...

    async def get_document_detail(
        self,
        source_id: str,
    ) -> DocumentDetail:
        """Получить полную карточку документа по ID.

        Args:
            source_id: Идентификатор документа в источнике.

        Returns:
            DocumentDetail — полная карточка с текстом, цитатами и оглавлением.

        Raises:
            NotFoundError: Документ не найден.
            SourceUnavailableError: Источник временно недоступен.
        """
        ...

    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """Просмотр иерархического рубрикатора.

        Args:
            parent_id: ID родительской рубрики. None = корневые рубрики.
            query: Опциональный поисковый запрос для фильтрации рубрик.

        Returns:
            Список узлов рубрикатора.

        Raises:
            NotFoundError: Рубрика не найдена.
        """
        ...

    async def get_toc(
        self,
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> list[TocNode]:
        """Получить оглавление документа.

        Args:
            document_id: ID документа.
            parent_section_id: ID родительского раздела. None = корневые разделы.
            query: Опциональный поисковый запрос для фильтрации разделов.

        Returns:
            Список узлов оглавления.

        Raises:
            NotFoundError: Документ или раздел не найден.
        """
        ...

    # ── Admin / Verification Methods ──────────────────────────────────

    async def admin_get_reference_counts(self) -> ReferenceCounts:
        """Get counts of all reference tables for verification."""
        ...

    async def admin_get_qdrant_status(self) -> AdminQdrantStatus:
        """Get Qdrant collections status for verification."""
        ...

    async def admin_get_document_status(self, publish_id: str) -> DocumentStatus:
        """Get full status of a document across DB and Qdrant."""
        ...


__all__ = [
    "AdminQdrantStatus",
    "DocumentStatus",
    "ODLServiceProtocol",
    "QdrantCollectionInfo",
    "ReferenceCounts",
]
