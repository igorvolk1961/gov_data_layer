"""ODLService Protocol — контракт для всех реализаций сервиса.

Определяет единый интерфейс бизнес-логики слоя.
MCP-сервер и REST-сервер работают через этот Protocol,
что позволяет подменять реализацию (заглушка → настоящий сервис)
без изменения транспортного слоя.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.models.models import (
    DocumentDetail,
    SearchContext,
    SearchResponse,
    TocNode,
    TopicNode,
)


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


__all__ = [
    "ODLServiceProtocol",
]
