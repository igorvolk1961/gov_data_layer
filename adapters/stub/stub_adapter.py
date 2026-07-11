"""StubAdapter — тривиальная реализация SourceAdapter для демонстрации шва."""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.base import SourceAdapter
from core.errors import InvalidInputError, NotFoundError
from core.models.models import (
    ConfidenceSignals,
    LegalStatus,
    OfficialDocument,
    SearchContext,
    SearchResult,
    Source,
    SourceAvailability,
    TocNode,
    TopicNode,
)
from core.observability.logger import get_logger

logger = get_logger(__name__)


class StubAdapter(SourceAdapter):
    """Stub-адаптер с фиктивными данными для тестирования шва адаптера."""

    def __init__(self) -> None:
        self._source_id = "stub"
        self._documents: dict[str, OfficialDocument] = {
            "doc-1": OfficialDocument(
                id="doc-1",
                title="Пример НПА №1",
                source=Source(
                    id="stub",
                    name="Stub Source",
                    url="https://example.gov.ru",
                ),
                url="https://example.gov.ru/doc-1",
                summary="Тестовый документ для демонстрации шва адаптера.",
                jurisdiction="федеральная",
                region=None,
                topic=["общие положения"],
                organization=["Минюст"],
                ingest_date=datetime.now(timezone.utc),
                valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
                legal_status=LegalStatus.ACTIVE,
            ),
            "doc-2": OfficialDocument(
                id="doc-2",
                title="Пример НПА №2",
                source=Source(
                    id="stub",
                    name="Stub Source",
                    url="https://example.gov.ru",
                ),
                url="https://example.gov.ru/doc-2",
                summary="Ещё один тестовый документ.",
                jurisdiction="региональная",
                region="Московская область",
                topic=["налоги"],
                organization=["ФНС"],
                ingest_date=datetime.now(timezone.utc),
                valid_from=datetime(2024, 6, 1, tzinfo=timezone.utc),
                valid_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
                legal_status=LegalStatus.ACTIVE,
            ),
        }
        # Topics derived from document topics
        self._topics: list[TopicNode] = [
            TopicNode(
                id="topic-root",
                name="Все рубрики",
                parent_id="",
                description="Корневая рубрика",
                child_count=2,
                document_count=2,
            ),
            TopicNode(
                id="topic-obshchie-polozheniya",
                name="Общие положения",
                parent_id="topic-root",
                description="Акты общего характера",
                child_count=0,
                document_count=1,
            ),
            TopicNode(
                id="topic-nalogi",
                name="Налоги и сборы",
                parent_id="topic-root",
                description="Налоговое законодательство",
                child_count=0,
                document_count=1,
            ),
        ]
        # TOC derived from documents
        self._toc_nodes: dict[str, list[TocNode]] = {
            "doc-1": [
                TocNode(
                    id="sec-1",
                    document_id="doc-1",
                    title="Глава 1. Общие положения",
                    parent_id="",
                    level=0,
                    child_count=2,
                ),
                TocNode(
                    id="sec-1-1",
                    document_id="doc-1",
                    title="Статья 1. Основные понятия",
                    parent_id="sec-1",
                    level=1,
                    child_count=0,
                ),
                TocNode(
                    id="sec-1-2",
                    document_id="doc-1",
                    title="Статья 2. Сфера применения",
                    parent_id="sec-1",
                    level=1,
                    child_count=0,
                ),
                TocNode(
                    id="sec-2",
                    document_id="doc-1",
                    title="Глава 2. Заключительные положения",
                    parent_id="",
                    level=0,
                    child_count=0,
                ),
            ],
            "doc-2": [
                TocNode(
                    id="sec-2-1",
                    document_id="doc-2",
                    title="Раздел I. Общие положения",
                    parent_id="",
                    level=0,
                    child_count=1,
                ),
                TocNode(
                    id="sec-2-1-1",
                    document_id="doc-2",
                    title="Статья 1. Налогоплательщики",
                    parent_id="sec-2-1",
                    level=1,
                    child_count=0,
                ),
            ],
        }

    @property
    def source_id(self) -> str:
        return self._source_id

    async def search(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> list[SearchResult]:
        """Search stub documents by title/summary.

        Args:
            query: Search query (case-insensitive substring match).
                   Empty string matches all documents.
            context: Optional search context. If filters are provided,
                     returns empty (stub does not support filtering).

        Returns:
            List of matching SearchResult objects.
        """
        if context is not None and (context.region or context.topic or context.organization):
            logger.warning(
                "StubAdapter does not support context filters — returning empty results",
                extra={
                    "region": context.region,
                    "topic": context.topic,
                    "organization": context.organization,
                },
            )
            return []
        results: list[SearchResult] = []
        now = datetime.now(timezone.utc)
        for doc in self._documents.values():
            if (
                query
                and query.lower() not in doc.title.lower()
                and query.lower() not in (doc.summary or "").lower()
            ):
                continue
            results.append(
                SearchResult(
                    id=doc.id,
                    title=doc.title,
                    snippet=(doc.summary or "")[:200],
                    url=doc.url,
                    source_name=doc.source.name,
                    jurisdiction=doc.jurisdiction,
                    region=doc.region,
                    topic=doc.topic,
                    organization=doc.organization,
                    ingest_date=doc.ingest_date,
                    legal_status=doc.legal_status,
                    confidence=ConfidenceSignals(
                        retrieval_relevance=0.95,
                        data_freshness=now,
                        source_availability=SourceAvailability.AVAILABLE,
                    ),
                )
            )
        return results

    async def get(self, document_id: str) -> OfficialDocument:
        doc = self._documents.get(document_id)
        if doc is None:
            raise NotFoundError(f"Document '{document_id}' not found in stub adapter")
        return doc

    async def normalize(self, raw: dict[str, object]) -> OfficialDocument:
        doc_id = raw.get("id")
        if doc_id is None:
            raise InvalidInputError("Missing required field 'id' in raw data")
        url = raw.get("url")
        if url is None:
            raise InvalidInputError("Missing required field 'url' in raw data")
        return OfficialDocument(
            id=str(doc_id),
            title=str(raw.get("title", "Untitled")),
            source=Source(
                id="stub",
                name="Stub Source",
                url="https://example.gov.ru",
            ),
            url=str(url),
            summary=raw.get("summary"),
            jurisdiction=raw.get("jurisdiction"),
            region=raw.get("region"),
            topic=raw.get("topic", []),
            organization=raw.get("organization", []),
            ingest_date=raw.get("ingest_date", datetime.now(timezone.utc)),
            valid_from=raw.get("valid_from"),
            valid_to=raw.get("valid_to"),
            legal_status=raw.get("legal_status", LegalStatus.UNKNOWN),
        )

    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """Просмотр рубрикатора на основе тем документов.

        When parent_id is None, returns root topics (parent_id == "").
        When parent_id is provided, returns only topics with that parent_id.
        """
        if parent_id is None:
            result = [t for t in self._topics if t.parent_id == ""]
        else:
            result = [t for t in self._topics if t.parent_id == parent_id]
        if query:
            result = [t for t in result if query.lower() in t.name.lower()]
        return result

    async def get_toc(
        self,
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> list[TocNode]:
        """Оглавление документа.

        When parent_section_id is None, returns root sections (parent_id == "").
        When parent_section_id is provided, returns only nodes with that parent_id.

        Raises:
            NotFoundError: Документ не найден.
        """
        nodes = self._toc_nodes.get(document_id)
        if nodes is None:
            raise NotFoundError(f"Document '{document_id}' not found")
        if parent_section_id is None:
            result = [n for n in nodes if n.parent_id == ""]
        else:
            result = [n for n in nodes if n.parent_id == parent_section_id]
        if query:
            result = [n for n in result if query.lower() in n.title.lower()]
        return result

    async def get_content(self, document_id: str) -> str:
        """Получить полный текст документа в markdown-подобном формате.

        Args:
            document_id: Идентификатор документа.

        Returns:
            Полный текст документа.

        Raises:
            NotFoundError: Документ не найден.
        """
        doc = self._documents.get(document_id)
        if doc is None:
            raise NotFoundError(f"Document '{document_id}' not found")
        return f"# {doc.title}\n\n{doc.summary or ''}\n\n(Stub content — будет заменён в Phase 4.5)"

    async def ingest(self) -> int:
        return len(self._documents)


__all__ = [
    "StubAdapter",
]
