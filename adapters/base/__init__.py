"""SourceAdapter Protocol — контракт для всех адаптеров источников данных."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.models.models import (
    OfficialDocument,
    SearchContext,
    SearchResult,
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


__all__ = [
    "SourceAdapter",
]
