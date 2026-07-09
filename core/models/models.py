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

    id: str = Field(description="Уникальный идентификатор источника")
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
    span_start: int | None = Field(
        default=None, description="Начальная позиция цитаты в документе"
    )
    span_end: int | None = Field(
        default=None, description="Конечная позиция цитаты в документе"
    )


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
    data_freshness: datetime = Field(
        description="Дата последнего инжеста данных в индекс"
    )
    legal_status: LegalStatus = Field(description="Юридический статус документа")
    source_availability: SourceAvailability = Field(
        description="Доступность источника на момент запроса"
    )


class OfficialDocument(BaseModel):
    """Canonical document model — entity with metadata."""

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}

    id: str = Field(description="Уникальный идентификатор документа")
    title: str = Field(description="Заголовок документа")
    source: Source = Field(description="Источник документа")
    url: str = Field(description="Прямая ссылка на документ")
    summary: str | None = Field(
        default=None, description="Краткое содержание/аннотация"
    )
    jurisdiction: str | None = Field(
        default=None, description="Юрисдикция (федеральная, региональная, ведомственная)"
    )
    topic: str | None = Field(default=None, description="Тематическая рубрика")
    organization: str | None = Field(
        default=None, description="Орган, принявший документ"
    )

    # Две оси времени
    ingest_date: datetime = Field(
        default_factory=_utc_now,
        description="Дата загрузки документа в индекс (свежесть копии)",
    )
    valid_from: datetime | None = Field(
        default=None, description="Дата начала юридической силы"
    )
    valid_to: datetime | None = Field(
        default=None,
        description="Дата окончания юридической силы (null = бессрочно)",
    )
    legal_status: LegalStatus = Field(
        default=LegalStatus.UNKNOWN,
        description="Юридический статус на момент инжеста",
    )


class SearchContext(BaseModel):
    """Контекст запроса — опциональные параметры для роутинга и фильтрации."""

    region: str | None = Field(
        default=None, description="Регион для фильтрации"
    )
    topic: str | None = Field(
        default=None, description="Тематическая рубрика"
    )
    organization: str | None = Field(
        default=None, description="Организация/ведомство"
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Максимальное количество результатов",
    )


class SearchResult(BaseModel):
    """Результат поиска — компактное представление документа."""

    id: str = Field(description="Идентификатор документа")
    title: str = Field(description="Заголовок")
    snippet: str = Field(description="Cниппет c релевантным контекстом")
    url: str = Field(description="Ссылка на документ")
    source_name: str = Field(description="Название источника")
    ingest_date: datetime = Field(description="Дата инжеста")
    legal_status: LegalStatus = Field(description="Юридический статус")
    confidence: ConfidenceSignals = Field(
        description="Сигналы уверенности для данного результата"
    )


class TopicNode(BaseModel):
    """Узел иерархического рубрикатора."""

    id: str = Field(description="Уникальный идентификатор рубрики")
    name: str = Field(description="Название рубрики")
    parent_id: str = Field(description="ID родительской рубрики")
    description: str | None = Field(
        default=None, description="Описание рубрики"
    )
    child_count: int = Field(
        default=0, description="Количество дочерних рубрик"
    )
    document_count: int = Field(
        default=0, description="Количество документов в рубрике"
    )


class TocNode(BaseModel):
    """Узел оглавления документа."""

    id: str = Field(description="Идентификатор раздела")
    document_id: str = Field(description="ID документа")
    title: str = Field(description="Заголовок раздела")
    parent_id: str = Field(description="ID родительского раздела")
    level: int = Field(ge=0, description="Уровень вложенности (0 = корень)")
    child_count: int = Field(
        default=0, description="Количество дочерних разделов"
    )
