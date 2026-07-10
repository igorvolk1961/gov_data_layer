"""Каноническая модель данных — Pydantic v2 схемы для всех сущностей слоя."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return current UTC datetime — helper for Pydantic default_factory."""
    return datetime.now(timezone.utc)


class LegalStatus(str, Enum):
    """Юридический статус нормативно-правового акта."""

    ACTIVE = "active"
    REVOKED = "revoked"
    MODIFIED = "modified"
    UNKNOWN = "unknown"


class SourceAvailability(str, Enum):
    """Доступность источника данных."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class Source(BaseModel):
    """Information about a data source."""

    id: str = Field(min_length=1, description="Уникальный идентификатор источника")
    name: str = Field(description="Человекочитаемое название источника")
    url: str = Field(description="Базовый URL источника")
    jurisdiction: str | None = Field(
        default=None,
        description="Юрисдикция (федеральная, региональная, ведомственная)",
    )


class Citation(BaseModel):
    """Citation linked to a source."""

    text: str = Field(description="Текст цитаты")
    source_id: str = Field(description="Идентификатор документа-источника")
    url: str = Field(description="Прямая ссылка на источник цитаты")
    span_start: int | None = Field(default=None, description="Начальная позиция цитаты в документе")
    span_end: int | None = Field(default=None, description="Конечная позиция цитаты в документе")


class ConfidenceSignals(BaseModel):
    """Confidence signals for a piece of data."""

    retrieval_relevance: float = Field(
        ge=0.0,
        le=1.0,
        description="Similarity score ретрива (косинусная близость)",
    )
    extraction_confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=1.0,
        description="Надёжность извлечения полей (если используется LLM)",
    )
    data_freshness: datetime = Field(description="Дата последнего инжеста данных в индекс")
    legal_status: LegalStatus = Field(description="Юридический статус документа")
    source_availability: SourceAvailability = Field(
        description="Доступность источника на момент запроса"
    )


class OfficialDocument(BaseModel):
    """Canonical document model — entity with metadata."""

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}

    id: str = Field(min_length=1, description="Уникальный идентификатор документа")
    title: str = Field(description="Заголовок документа")
    source: Source = Field(description="Источник документа")
    url: str = Field(min_length=1, description="Прямая ссылка на документ")
    summary: str | None = Field(default=None, description="Краткое содержание/аннотация")
    jurisdiction: str | None = Field(
        default=None, description="Юрисдикция (федеральная, региональная, ведомственная)"
    )
    topic: str | None = Field(default=None, description="Тематическая рубрика")
    organization: str | None = Field(default=None, description="Орган, принявший документ")

    # Две оси времени
    ingest_date: datetime = Field(
        default_factory=_utc_now,
        description="Дата загрузки документа в индекс (свежесть копии)",
    )
    valid_from: datetime | None = Field(default=None, description="Дата начала юридической силы")
    valid_to: datetime | None = Field(
        default=None,
        description="Дата окончания юридической силы (null = бессрочно)",
    )
    legal_status: LegalStatus = Field(
        default=LegalStatus.UNKNOWN,
        description="Юридический статус на момент инжеста",
    )


class SearchContext(BaseModel):
    """Контекст запроса — опциональные параметры для роутинга и фильтрации.

    query передаётся отдельным параметром в инструменты MCP и содержит
    свободный текст вопроса/интент пользователя. SearchContext содержит
    только структурированные параметры для фильтрации и роутинга.

    Все поля опциональны — при неполноте контекста слой работает
    best-effort с честным сигналом (мягкая деградация).
    """

    region: str | None = Field(
        default=None,
        description="Географический регион (город, область, край). Пример: 'Московская область', 'г. Москва'",
    )
    topic: str | None = Field(
        default=None,
        description="Тематическая рубрика. Пример: 'налоги', 'социальное обеспечение', 'земельное право'",
    )
    organization: str | None = Field(
        default=None,
        description="Орган, принявший документ. Пример: 'ФНС', 'Законодательное собрание Московской области'",
    )
    official_only: bool = Field(
        default=False,
        description="Только официальные источники (без аналитики и комментариев)",
    )
    max_age_days: int | None = Field(
        default=None,
        ge=1,
        description="Максимальный возраст документа в днях (окно актуальности). Пример: 30 — только документы не старше 30 дней",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Максимальное количество результатов на страницу",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Смещение для пагинации (количество пропущенных результатов). "
        "Агент начинает с offset=0, затем использует offset += max_results "
        "для получения следующей страницы, пока offset < total_count",
    )


class SearchResult(BaseModel):
    """Результат поиска — компактное представление документа."""

    id: str = Field(min_length=1, description="Идентификатор документа")
    title: str = Field(description="Заголовок")
    snippet: str = Field(description="Cниппет c релевантным контекстом")
    url: str = Field(description="Ссылка на документ")
    source_name: str = Field(description="Название источника")
    ingest_date: datetime = Field(description="Дата инжеста")
    legal_status: LegalStatus = Field(description="Юридический статус")
    confidence: ConfidenceSignals = Field(description="Сигналы уверенности для данного результата")


class SearchResponse(BaseModel):
    """Ответ на поисковый запрос — результаты с мета-информацией для пагинации.

    Содержит как сами результаты, так и общее количество найденных документов,
    чтобы агент мог вычислить следующее смещение для продолжения пагинации.
    """

    results: list[SearchResult] = Field(description="Результаты поиска на текущей странице")
    total_count: int = Field(
        ge=0,
        description="Общее количество результатов, удовлетворяющих запросу (без учёта пагинации). "
        "Агент использует: если offset + len(results) < total_count, "
        "то можно запросить следующую страницу с offset += max_results",
    )
    offset: int = Field(
        ge=0,
        description="Смещение, использованное в запросе (зеркалится из SearchContext.offset "
        "для удобства агента)",
    )


class TopicNode(BaseModel):
    """Узел иерархического рубрикатора."""

    id: str = Field(min_length=1, description="Уникальный идентификатор рубрики")
    name: str = Field(description="Название рубрики")
    parent_id: str = Field(description="ID родительской рубрики")
    description: str | None = Field(default=None, description="Описание рубрики")
    child_count: int = Field(default=0, description="Количество дочерних рубрик")
    document_count: int = Field(default=0, description="Количество документов в рубрике")


class TocNode(BaseModel):
    """Узел оглавления документа."""

    id: str = Field(min_length=1, description="Идентификатор раздела")
    document_id: str = Field(description="ID документа")
    title: str = Field(description="Заголовок раздела")
    parent_id: str = Field(description="ID родительского раздела")
    level: int = Field(ge=0, description="Уровень вложенности (0 = корень)")
    child_count: int = Field(default=0, description="Количество дочерних разделов")
