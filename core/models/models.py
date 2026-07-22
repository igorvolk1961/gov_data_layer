"""Каноническая модель данных — Pydantic v2 схемы для всех сущностей слоя."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_serializer


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
    """Citation linked to a source, with optional section path for large documents."""

    text: str = Field(description="Текст цитаты")
    source_id: str = Field(description="Идентификатор документа-источника")
    url: str = Field(description="Прямая ссылка на источник цитаты")
    section: list[str] | None = Field(
        default=None,
        description="Путь к разделу от корня документа. "
        "Пример: ['Раздел I', 'Глава 2', 'Статья 10']. "
        "Позволяет агенту понять контекст цитаты и навигироваться "
        "по иерархии документа без дополнительного запроса",
    )
    span_start: int | None = Field(default=None, description="Начальная позиция цитаты в документе")
    span_end: int | None = Field(default=None, description="Конечная позиция цитаты в документе")


class ConfidenceSignals(BaseModel):
    """Разложенные сигналы уверенности для результата поиска.

    Свёртку в единую меру (answerability) делает вызывающий агент
    (принцип механизм/политика).

    Сигналы:
    - retrieval_relevance: насколько результат релевантен запросу
    - data_freshness: когда данные загружены в индекс (свежесть копии)
    - source_availability: доступность источника на момент запроса

    legal_status не включён — это метаданные документа, а не сигнал
    уверенности; он доступен в SearchResult.legal_status и
    OfficialDocument.legal_status.

    extraction_confidence не включён — в текущей реализации все адаптеры
    используют детерминированный парсинг (без LLM), поэтому сигнал всегда
    равен 1.0 и не несёт информации. При появлении LLM-извлечения полей
    сигнал может быть добавлен как dict[str, float] — уверенность по
    каждому полю отдельно (см. ADR раздел 7).
    """

    retrieval_relevance: float = Field(
        ge=0.0,
        le=1.0,
        description="Similarity score ретрива (косинусная близость). "
        "Единственный обязательный сигнал — всегда доступен после поиска.",
    )
    data_freshness: datetime | None = Field(
        default=None,
        description="Дата вступления в силу раздела документа, которому "
        "принадлежит чанк (valid_from). None если дата неизвестна.",
    )
    source_availability: SourceAvailability = Field(
        description="Доступность источника на момент запроса. "
        "Может различаться между результатами при агрегации из нескольких источников.",
    )


class OfficialDocument(BaseModel):
    """Canonical document model — entity with metadata."""

    # Pydantic v2 uses ISO format by default for datetime serialization,
    # which matches the previous json_encoders override. Explicit serializer
    # ensures consistent behavior for model_dump_json() and json.dumps().
    @field_serializer("created_at", "valid_from", "valid_to", "publish_date")
    @classmethod
    def serialize_datetime(cls, v: datetime | None) -> str | None:
        return v.isoformat() if v else None

    id: str = Field(min_length=1, description="Уникальный идентификатор документа")
    title: str = Field(description="Заголовок документа")
    source: Source = Field(description="Источник документа")
    url: str = Field(min_length=1, description="Прямая ссылка на документ")
    summary: str | None = Field(default=None, description="Краткое содержание/аннотация")
    jurisdiction: str | None = Field(
        default=None, description="Юрисдикция (федеральная, региональная, ведомственная)"
    )
    region: str | None = Field(
        default=None,
        description="Географический регион, к которому относится документ. "
        "Пример: 'Московская область', 'г. Москва'. "
        "Для федеральных документов — null.",
    )
    region_id: str | None = Field(
        default=None,
        description="UUID региона из таблицы region (государственный классификатор). "
        "Устанавливается при инжесте через get_or_create_region.",
    )
    topic: list[str] = Field(
        default_factory=list,
        description="Тематические рубрики. Документ может относиться к нескольким рубрикам. "
        "Пример: ['налоги', 'земельное право']",
    )
    organization: str | None = Field(
        default=None,
        description="Орган, принявший документ. Пример: 'Минюст России'",
    )
    organization_id: str | None = Field(
        default=None,
        description="GUID органа, принявшего документ, из API источника. "
        "Используется как external_id в таблице organization. "
        "Пример: '3fa85f64-5717-4562-b3fc-2c963f66afa6'",
    )
    document_type: str | None = Field(
        default=None,
        description="Вид документа. Пример: 'Приказ', 'Постановление', 'Федеральный закон'",
    )
    document_type_id: str | None = Field(
        default=None,
        description="GUID вида документа из API источника. "
        "Используется как external_id в таблице document_type. "
        "Пример: '3fa85f64-5717-4562-b3fc-2c963f66afa6'",
    )

    # Две оси времени
    created_at: datetime = Field(
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

    # Новые общие поля (из API pravo.gov.ru)
    document_number: str | None = Field(
        default=None,
        description="Номер документа (НПА). Пример: '668н', '154н', '2330'",
    )
    publish_id: str | None = Field(
        default=None,
        description="Номер электронного опубликования (eoNumber). Пример: '0001202012230060'",
    )
    publish_date: datetime | None = Field(
        default=None,
        description="Дата публикации документа (из publishDateShort API pravo.gov.ru). "
        "Отличается от created_at — это дата первой официальной публикации.",
    )

    # Source-специфичные атрибуты (не маппятся в канонические поля)
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-специфичные атрибуты документа, "
        "не маппящиеся в канонические поля. "
        "Пример для pravo.gov.ru: pdf_url, pdf_pages, jd_reg_number, jd_reg_date. "
        "Позволяет расширять модель без изменения схемы.",
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
    region_id: str | None = Field(
        default=None,
        description="Resolved region UUID for Qdrant filtering. "
        "Set internally by ODLService after trigram search.",
    )
    region_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Trigram similarity score of the resolved region. "
        "Used as honesty signal in the response confidence.",
    )
    organization: list[str] | None = Field(
        default=None,
        description="Органы для фильтрации (OR-семантика — совпадение с любым). "
        "Пример: ['ФНС', 'Минюст России']. "
        "None = фильтр не применяется.",
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
    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Минимальный порог релевантности (cosine similarity). "
        "Задаётся агентом (политика). Результаты ниже порога отбрасываются. "
        "None = не фильтровать (честный сигнал — слой возвращает все результаты, "
        "агент сам решает, какой порог acceptable). "
        "Пример: 0.5 — только результаты с score >= 0.5",
    )


class SearchResult(BaseModel):
    """Результат поиска — компактное представление документа.

    Содержит все метаданные, необходимые агенту для фильтрации и ранжирования
    без дополнительного вызова get_document_detail() (N+1 prevention).
    """

    id: str = Field(min_length=1, description="Идентификатор документа")
    title: str = Field(description="Заголовок")
    snippet: str = Field(description="Cниппет c релевантным контекстом")
    url: str = Field(description="Ссылка на документ")
    source_name: str = Field(description="Название источника")
    jurisdiction: str | None = Field(
        default=None,
        description="Юрисдикция (федеральная, региональная, ведомственная). "
        "Позволяет агенту фильтровать результаты без N+1 get_document_detail().",
    )
    region: str | None = Field(
        default=None,
        description="Географический регион документа. "
        "Позволяет агенту фильтровать результаты без N+1 get_document_detail().",
    )
    topic: list[str] = Field(
        default_factory=list,
        description="Тематические рубрики. "
        "Позволяет агенту фильтровать результаты без N+1 get_document_detail().",
    )
    organization: str | None = Field(
        default=None,
        description="Орган, принявший документ. "
        "Пример: 'Минтруд России'. "
        "Позволяет агенту фильтровать результаты без N+1 get_document_detail().",
    )
    created_at: datetime = Field(description="Дата загрузки документа в индекс (свежесть копии)")
    legal_status: LegalStatus = Field(description="Юридический статус")
    confidence: ConfidenceSignals = Field(description="Сигналы уверенности для данного результата")

    # Поля для фильтрации без N+1 (из OfficialDocument)
    document_number: str | None = Field(
        default=None,
        description="Номер документа (НПА). Пример: '668н', '154н', '2330'. "
        "Позволяет агенту фильтровать результаты без N+1 get_document_detail().",
    )
    document_type: str | None = Field(
        default=None,
        description="Вид документа. Пример: 'Приказ', 'Постановление', 'Федеральный закон'. "
        "Позволяет агенту фильтровать результаты без N+1 get_document_detail().",
    )


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
    missing_context: str | None = Field(
        default=None,
        description="Indicates what context is missing from the query, "
        "e.g. 'region'. Set when region is not specified but "
        "regional documents exist for the requested rubric.",
    )
    suggested_clarification_prompt: str | None = Field(
        default=None,
        description="Prompt for the agent to ask the user for missing context. "
        "Example: 'Для уточнения запроса, пожалуйста, укажите Ваш регион проживания'",
    )


class DocumentDetail(BaseModel):
    """Полная карточка документа — ответ get_document_detail().

    Агент вызывает get_document_detail() после выбора документа из результатов поиска.
    Содержит плоские метаданные (без вложенного OfficialDocument), цитаты
    с привязкой к разделам и оглавление.

    Агент НЕ видит OfficialDocument — это внутренняя модель слоя.
    """

    # Плоские метаданные (агент не видит OfficialDocument)
    id: str = Field(min_length=1, description="Идентификатор документа")
    title: str = Field(description="Заголовок документа")
    url: str = Field(description="Прямая ссылка на документ")
    source_name: str = Field(description="Название источника")
    jurisdiction: str | None = Field(
        default=None, description="Юрисдикция (федеральная, региональная, ведомственная)"
    )
    region: str | None = Field(
        default=None,
        description="Географический регион, к которому относится документ. "
        "Пример: 'Московская область', 'г. Москва'. "
        "Для федеральных документов — null.",
    )
    topic: list[str] = Field(
        default_factory=list,
        description="Тематические рубрики. Документ может относиться к нескольким рубрикам.",
    )
    organization: str | None = Field(
        default=None,
        description="Орган, принявший документ. Пример: 'Минтруд России'.",
    )
    created_at: datetime = Field(description="Дата загрузки документа в индекс (свежесть копии)")
    valid_from: datetime | None = Field(default=None, description="Дата начала юридической силы")
    valid_to: datetime | None = Field(
        default=None,
        description="Дата окончания юридической силы (null = бессрочно)",
    )
    legal_status: LegalStatus = Field(description="Юридический статус")

    # Поля из OfficialDocument (для агентской фильтрации без N+1)
    document_number: str | None = Field(
        default=None,
        description="Номер документа (НПА). Пример: '668н', '154н', '2330'.",
    )
    document_type: str | None = Field(
        default=None,
        description="Вид документа. Пример: 'Приказ', 'Постановление', 'Федеральный закон'.",
    )

    # Содержимое (то, ради чего агент вызывает get_document_detail)
    citations: list[Citation] = Field(
        default_factory=list,
        description="Цитаты с привязкой к разделам документа. "
        "Каждая цитата содержит текст, ссылку на источник и путь к разделу. "
        "Агент использует их для точного provenance в ответе пользователю.",
    )


class TopicNode(BaseModel):
    """Узел иерархического рубрикатора.

    Convention: root-level topics use `parent_id=""` (empty string),
    not `None`. This ensures consistent filtering across all adapters:
    callers pass `parent_id=""` to query root topics, or `parent_id=None`
    to get all topics regardless of depth.
    """

    id: str = Field(min_length=1, description="Уникальный идентификатор рубрики")
    name: str = Field(description="Название рубрики")
    parent_id: str = Field(
        description="ID родительской рубрики. Empty string ('') = root-level topic.",
    )
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


class DocumentChunk(BaseModel):
    """Чанк документа для хранения в Qdrant.

    Содержит текст, эмбеддинг, section_path и метаданные связей
    с записями в PostgreSQL (doc_uuid, section_uuids).
    """

    id: str = Field(description="UUID чанка (point id в Qdrant)")
    document_id: str = Field(description="ID документа (source_id-publish_id)")
    doc_uuid: str = Field(description="UUID документа в PostgreSQL")
    text: str = Field(description="Текст чанка")
    embedding: list[float] | None = Field(default=None, description="Вектор эмбеддинга")
    section_path: list[str] = Field(default_factory=list, description="Путь по разделам")
    section_external_ids: list[str] = Field(default_factory=list, description="Внешние ID разделов")
    section_uuids: list[str] = Field(default_factory=list, description="UUID разделов в PostgreSQL")
    chunk_index: int = Field(default=0, ge=0, description="Порядковый номер чанка в документе")
    section_chunk_index: int = Field(
        default=0,
        ge=0,
        description="Порядковый номер чанка в пределах его раздела (section_path). "
        "Используется для сборки цитат: чанки одного раздела упорядочиваются "
        "по section_chunk_index и объединяются в одну цитату.",
    )
    data_freshness: datetime | None = Field(
        default=None,
        description="Дата свежести данных чанка. Для НПА — дата вступления в силу "
        "(valid_from) документа/раздела. None если дата неизвестна.",
    )
    not_actual_since: date | None = Field(
        default=None,
        description="Дата, после которой чанк перестаёт быть актуальным. "
        "Устанавливается при обработке документа, отменяющего/изменяющего "
        "раздел, к которому относится чанк. По умолчанию None (актуален). "
        "При поиске фильтр: not_actual_since IS NULL OR not_actual_since > now().",
    )
    region: str | None = Field(
        default=None,
        description="Географический регион, к которому относится документ. "
        "Заполняется из OfficialDocument.region при инжесте.",
    )
    region_id: str | None = Field(
        default=None,
        description="UUID региона из таблицы region. "
        "Заполняется из OfficialDocument.region_id при инжесте. "
        "Используется для фильтрации в Qdrant.",
    )
    topic_ids: list[str] = Field(
        default_factory=list,
        description="UUID рубрик (топиков), связанных с чанком. "
        "Заполняется в link_chunks_to_topics() по косинусной близости текста чанка "
        "с названиями рубрик. Используется для фильтрации в Qdrant.",
    )
    topic_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Маппинг topic_id → score (косинусная близость чанка к рубрике). "
        "Заполняется в link_chunks_to_topics(). "
        "Используется для комбинированного ранжирования при поиске.",
    )


class RegionNode(BaseModel):
    """A node in the hierarchical region tree.

    Mirrors TopicNode structure for consistency in API responses.
    """

    id: str = Field(min_length=1, description="Уникальный идентификатор региона")
    name: str = Field(description="Название региона")
    parent_id: str = Field(
        description="ID родительского региона. Empty string ('') = root-level",
    )
    description: str | None = Field(default=None, description="Описание региона")
    child_count: int = Field(default=0, ge=0, description="Количество дочерних регионов")
    document_count: int = Field(
        default=0, ge=0, description="Количество документов, связанных с регионом"
    )


class TopicPoint(BaseModel):
    """Topic (rubric) vector point for storage in Qdrant topics collection.

    Stores the topic name and embedding vector for semantic retrieval.
    """

    id: str = Field(min_length=1, description="Qdrant point ID (topic external_id)")
    topic_id: str = Field(min_length=1, description="UUID of the topic in PostgreSQL")
    name: str = Field(description="Topic name")
    embedding: list[float] | None = Field(default=None, description="Topic embedding vector")
