"""Unit tests for StubAdapter (adapters/stub/__init__.py).

Tests cover:
- search(): matching, case-insensitivity, empty results, context filtering
- get(): existing / non-existing documents
- normalize(): minimal data, full data, missing id
- ingest(): document count
- source_id property
- ConfidenceSignals in search results
"""

from __future__ import annotations

import pytest

from adapters.stub import StubAdapter
from core.errors import InvalidInputError, NotFoundError
from core.models.models import (
    ConfidenceSignals,
    LegalStatus,
    OfficialDocument,
    SearchContext,
    SearchResult,
    SourceAvailability,
)


@pytest.fixture
def adapter() -> StubAdapter:
    return StubAdapter()


# ──────────────────────────────────────────────
#  source_id
# ──────────────────────────────────────────────


class TestSourceId:
    def test_returns_stub(self, adapter: StubAdapter) -> None:
        assert adapter.source_id == "stub"


# ──────────────────────────────────────────────
#  search
# ──────────────────────────────────────────────


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_by_title(self, adapter: StubAdapter) -> None:
        results = await adapter.search("НПА")
        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)

    @pytest.mark.asyncio
    async def test_search_by_summary(self, adapter: StubAdapter) -> None:
        results = await adapter.search("тестовый")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, adapter: StubAdapter) -> None:
        results_lower = await adapter.search("нпа")
        results_upper = await adapter.search("НПА")
        assert len(results_lower) == 2
        assert len(results_upper) == 2

    @pytest.mark.asyncio
    async def test_search_partial_match(self, adapter: StubAdapter) -> None:
        """Search for a substring that appears in one document."""
        results = await adapter.search("№1")
        assert len(results) == 1
        assert results[0].id == "doc-1"

    @pytest.mark.asyncio
    async def test_search_no_match(self, adapter: StubAdapter) -> None:
        results = await adapter.search("qwerty123456")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_empty_query(self, adapter: StubAdapter) -> None:
        """Empty query matches all documents (explicitly handled)."""
        results = await adapter.search("")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_with_context_no_filters(self, adapter: StubAdapter) -> None:
        """Context without filters should not affect search."""
        ctx = SearchContext()
        results = await adapter.search("НПА", context=ctx)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_with_context_filters_returns_empty(self, adapter: StubAdapter) -> None:
        """Context with filters triggers stub warning and returns empty."""
        ctx = SearchContext(region="Москва", topic="налоги")
        results = await adapter.search("НПА", context=ctx)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_result_confidence_signals(self, adapter: StubAdapter) -> None:
        results = await adapter.search("НПА")
        assert len(results) == 2
        for r in results:
            assert isinstance(r.confidence, ConfidenceSignals)
            assert r.confidence.retrieval_relevance == 0.95
            assert r.confidence.source_availability == SourceAvailability.AVAILABLE

    @pytest.mark.asyncio
    async def test_search_result_fields(self, adapter: StubAdapter) -> None:
        results = await adapter.search("№1")
        assert len(results) == 1
        r = results[0]
        assert r.id == "doc-1"
        assert r.title == "Пример НПА №1"
        assert r.source_name == "Stub Source"
        assert r.url == "https://example.gov.ru/doc-1"
        assert r.legal_status == LegalStatus.ACTIVE


# ──────────────────────────────────────────────
#  get
# ──────────────────────────────────────────────


class TestGet:
    @pytest.mark.asyncio
    async def test_get_existing(self, adapter: StubAdapter) -> None:
        doc = await adapter.get("doc-1")
        assert isinstance(doc, OfficialDocument)
        assert doc.id == "doc-1"
        assert doc.title == "Пример НПА №1"
        assert doc.source.id == "stub"
        assert doc.legal_status == LegalStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_get_existing_doc2(self, adapter: StubAdapter) -> None:
        doc = await adapter.get("doc-2")
        assert doc.id == "doc-2"
        assert doc.organization == "ФНС"
        assert doc.jurisdiction == "региональная"
        # doc-2 has valid_to
        assert doc.valid_to is not None

    @pytest.mark.asyncio
    async def test_get_non_existing_raises_not_found(self, adapter: StubAdapter) -> None:
        with pytest.raises(NotFoundError) as exc_info:
            await adapter.get("doc-999")
        assert "doc-999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_empty_id_raises_not_found(self, adapter: StubAdapter) -> None:
        with pytest.raises(NotFoundError):
            await adapter.get("")


# ──────────────────────────────────────────────
#  normalize
# ──────────────────────────────────────────────


class TestNormalize:
    @pytest.mark.asyncio
    async def test_normalize_minimal(self, adapter: StubAdapter) -> None:
        doc = await adapter.normalize({"id": "new-doc", "url": "https://example.gov/new"})
        assert isinstance(doc, OfficialDocument)
        assert doc.id == "new-doc"
        assert doc.title == "Untitled"  # default
        assert doc.source.id == "stub"
        assert doc.url == "https://example.gov/new"

    @pytest.mark.asyncio
    async def test_normalize_full(self, adapter: StubAdapter) -> None:
        raw = {
            "id": "new-doc",
            "title": "My Title",
            "url": "https://example.gov.ru/new",
        }
        doc = await adapter.normalize(raw)
        assert doc.id == "new-doc"
        assert doc.title == "My Title"
        assert doc.url == "https://example.gov.ru/new"

    @pytest.mark.asyncio
    async def test_normalize_missing_id_raises_invalid_input(self, adapter: StubAdapter) -> None:
        with pytest.raises(InvalidInputError) as exc_info:
            await adapter.normalize({"title": "No ID", "url": "https://example.gov/doc"})
        assert "id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_normalize_missing_url_raises_invalid_input(self, adapter: StubAdapter) -> None:
        with pytest.raises(InvalidInputError) as exc_info:
            await adapter.normalize({"id": "new-doc"})
        assert "url" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_normalize_empty_dict_raises_invalid_input(self, adapter: StubAdapter) -> None:
        with pytest.raises(InvalidInputError):
            await adapter.normalize({})


# ──────────────────────────────────────────────
#  ingest
# ──────────────────────────────────────────────


class TestIngest:
    @pytest.mark.asyncio
    async def test_ingest_returns_document_count(self, adapter: StubAdapter) -> None:
        count = await adapter.ingest()
        assert count == 2

    @pytest.mark.asyncio
    async def test_ingest_always_returns_same_count(self, adapter: StubAdapter) -> None:
        count1 = await adapter.ingest()
        count2 = await adapter.ingest()
        assert count1 == count2 == 2
