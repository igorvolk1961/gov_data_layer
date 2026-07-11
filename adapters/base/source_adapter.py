"""SourceAdapter Protocol — контракт для всех адаптеров источников данных."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.models.models import (
    OfficialDocument,
    SearchContext,
    SearchResult,
    TocNode,
    TopicNode,
)


@runtime_checkable
class SourceAdapter(Protocol):
    """Протокол адаптера источника данных.

    Каждый источник (pravo.gov.ru, nalog.ru и т.д.) реализует этот протокол.
    Слой (роутер) вызывает эти методы, не зная деталей источника.
    """

    @property
    def source_id(self) -> str:
        """Уникальный идентификатор источника (например, 'pravo', 'nalog')."""
        ...

    async def search(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> list[SearchResult]:
        """Поиск по источнику.

        Args:
            query: Поисковый запрос.
            context: Опциональные параметры фильтрации (регион, тема и т.д.).

        Returns:
            Список компактных результатов поиска.

        Raises:
            SourceUnavailableError: Источник временно недоступен.
            InvalidInputError: Некорректный запрос.
        """
        ...

    async def get(self, document_id: str) -> OfficialDocument:
        """Получить полную карточку документа по ID.

        Args:
            document_id: Идентификатор документа в источнике.

        Returns:
            Полная каноническая модель документа.

        Raises:
            NotFoundError: Документ не найден.
            SourceUnavailableError: Источник временно недоступен.
        """
        ...

    async def normalize(self, raw: dict[str, object]) -> OfficialDocument:
        """Привести сырые данные источника к канонической модели.

        Args:
            raw: Сырые данные от источника (JSON, HTML и т.д.).

        Returns:
            Нормализованный документ в канонической модели.
        """
        ...

    async def ingest(self) -> int:
        """Загрузить новые/обновлённые документы из источника в индекс.

        Returns:
            Количество загруженных/обновлённых документов.

        Raises:
            SourceUnavailableError: Источник временно недоступен.
        """
        ...

    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """Просмотр иерархического рубрикатора источника.

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

    async def get_content(self, document_id: str) -> str:
        """Получить полный текст документа в markdown-подобном формате.

        Args:
            document_id: Идентификатор документа.

        Returns:
            Полный текст документа.

        Raises:
            NotFoundError: Документ не найден.
        """
        ...


__all__ = [
    "SourceAdapter",
]
