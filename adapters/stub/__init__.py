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
                topic="общие положения",
                organization="Минюст",
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
                topic="налоги",
                organization="ФНС",
                ingest_date=datetime.now(timezone.utc),
                valid_from=datetime(2024, 6, 1, tzinfo=timezone.utc),
                valid_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
                legal_status=LegalStatus.ACTIVE,
            ),
        }

    @property
    def source_id(self) -> str:
        return self._source_id

    async def search(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> list[SearchResult]:
        if context is not None and (context.region or context.topic or context.organization):
            logger.warning(
                "StubAdapter does not support context filters — returning empty results",
                extra={"region": context.region, "topic": context.topic, "organization": context.organization},
            )
            return []
        results: list[SearchResult] = []
        now = datetime.now(timezone.utc)
        for doc in self._documents.values():
            if query.lower() in doc.title.lower() or query.lower() in (doc.summary or "").lower():
                results.append(
                    SearchResult(
                        id=doc.id,
                        title=doc.title,
                        snippet=(doc.summary or "")[:200],
                        url=doc.url,
                        source_name=doc.source.name,
                        ingest_date=doc.ingest_date,
                        legal_status=doc.legal_status,
                        confidence=ConfidenceSignals(
                            retrieval_relevance=0.95,
                            extraction_confidence=1.0,
                            data_freshness=now,
                            legal_status=doc.legal_status,
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
        # TODO: Map all OfficialDocument fields from raw source data
        doc_id = raw.get("id")
        if doc_id is None:
            raise InvalidInputError("Missing required field 'id' in raw data")
        return OfficialDocument(
            id=str(doc_id),
            title=str(raw.get("title", "Untitled")),
            source=Source(
                id="stub",
                name="Stub Source",
                url="https://example.gov.ru",
            ),
            url=str(raw.get("url", "")),
        )

    async def ingest(self) -> int:
        return len(self._documents)
