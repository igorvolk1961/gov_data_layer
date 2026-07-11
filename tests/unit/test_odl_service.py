"""Tests for ODLService — content-rich checks on field types and non-emptiness."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.stub import StubAdapter
from core.errors import NotFoundError
from core.models.models import (
    Citation,
    ConfidenceSignals,
    DocumentDetail,
    LegalStatus,
    SearchContext,
    SearchResponse,
    SearchResult,
    TocNode,
    TopicNode,
)
from core.odl_service import ODLService

# Apply asyncio marker to all async tests in this module
pytestmark = pytest.mark.asyncio


@pytest.fixture
def tracer_mock() -> MagicMock:
    """Create a no-op tracer mock for injection into ODLService."""
    span_mock = MagicMock()
    span_mock.__enter__.return_value = span_mock
    tracer = MagicMock()
    tracer.trace.return_value = span_mock
    return tracer


@pytest.fixture
def service(tracer_mock: MagicMock) -> ODLService:
    """ODLService with StubAdapter and a no-op tracer."""
    return ODLService(adapters=[StubAdapter()], tracer=tracer_mock)


# -- search_documents ----------------------------------------------------------


class TestSearchDocuments:
    """search_documents -- content-rich checks."""

    async def test_returns_search_response(self, service: ODLService) -> None:
        response = await service.search_documents("тест")
        assert isinstance(response, SearchResponse)

    async def test_results_are_search_result_instances(
        self,
        service: ODLService,
    ) -> None:
        response = await service.search_documents("тест")
        assert len(response.results) > 0
        for r in response.results:
            assert isinstance(r, SearchResult)

    async def test_result_fields_are_non_empty(
        self,
        service: ODLService,
    ) -> None:
        response = await service.search_documents("тест")
        for r in response.results:
            assert r.id, "id must be non-empty"
            assert r.title, "title must be non-empty"
            assert r.snippet, "snippet must be non-empty"
            assert r.url, "url must be non-empty"
            assert r.source_name, "source_name must be non-empty"

    async def test_result_fields_have_correct_types(
        self,
        service: ODLService,
    ) -> None:
        response = await service.search_documents("тест")
        for r in response.results:
            assert isinstance(r.id, str)
            assert isinstance(r.title, str)
            assert isinstance(r.snippet, str)
            assert isinstance(r.url, str)
            assert isinstance(r.source_name, str)
            assert isinstance(r.jurisdiction, str | None)
            assert isinstance(r.region, str | None)
            assert isinstance(r.topic, list)
            assert isinstance(r.organization, list)
            assert isinstance(r.legal_status, LegalStatus)
            assert isinstance(r.confidence, ConfidenceSignals)

    async def test_total_count_matches_results_length(
        self,
        service: ODLService,
    ) -> None:
        response = await service.search_documents("тест")
        assert response.total_count == len(response.results)

    async def test_offset_from_context(self, service: ODLService) -> None:
        """Offset is passed through to SearchResponse (passthrough, not pagination).

        The StubAdapter returns all matching results without slicing, so this
        test verifies that ODLService correctly mirrors SearchContext.offset
        into SearchResponse.offset, not that actual pagination occurs.
        """
        ctx = SearchContext(offset=5)
        response = await service.search_documents("тест", context=ctx)
        assert response.offset == 5

    async def test_search_with_query_filter(
        self,
        service: ODLService,
    ) -> None:
        """Query filters results -- at least one result for a known query."""
        response = await service.search_documents("НПА")
        assert len(response.results) > 0

    async def test_search_no_match_returns_empty(
        self,
        service: ODLService,
    ) -> None:
        response = await service.search_documents(
            "xyznonexistent_12345",
        )
        assert len(response.results) == 0
        assert response.total_count == 0

    async def test_tracing_is_called(
        self,
        service: ODLService,
        tracer_mock: MagicMock,
    ) -> None:
        """Verify that search_documents calls tracer.trace with correct args."""
        await service.search_documents("тест")
        tracer_mock.trace.assert_called_once_with(
            "search_documents",
            query="тест",
        )

    async def test_tracing_with_context(
        self,
        service: ODLService,
        tracer_mock: MagicMock,
    ) -> None:
        """Verify context is forwarded to the adapter and traced."""
        ctx = SearchContext(offset=3)
        # Spy on adapter.search to verify context is forwarded
        service._adapters[0].search = AsyncMock(wraps=service._adapters[0].search)  # type: ignore[method-assign]
        await service.search_documents("тест", context=ctx)
        service._adapters[0].search.assert_awaited_once_with("тест", ctx)
        tracer_mock.trace.assert_called_once_with(
            "search_documents",
            query="тест",
        )


# -- get_document_detail -------------------------------------------------------


class TestGetDocumentDetail:
    """get_document_detail -- content-rich checks."""

    async def test_returns_document_detail(self, service: ODLService) -> None:
        detail = await service.get_document_detail("doc-1")
        assert isinstance(detail, DocumentDetail)

    async def test_metadata_fields_non_empty(
        self,
        service: ODLService,
    ) -> None:
        detail = await service.get_document_detail("doc-1")
        assert detail.id, "id must be non-empty"
        assert detail.title, "title must be non-empty"
        assert detail.url, "url must be non-empty"
        assert detail.source_name, "source_name must be non-empty"

    async def test_metadata_fields_have_correct_types(
        self,
        service: ODLService,
    ) -> None:
        detail = await service.get_document_detail("doc-1")
        assert isinstance(detail.id, str)
        assert isinstance(detail.title, str)
        assert isinstance(detail.url, str)
        assert isinstance(detail.source_name, str)
        assert isinstance(detail.jurisdiction, str | None)
        assert isinstance(detail.region, str | None)
        assert isinstance(detail.topic, list)
        assert isinstance(detail.organization, list)
        assert isinstance(detail.legal_status, LegalStatus)

    async def test_content_is_non_empty(self, service: ODLService) -> None:
        detail = await service.get_document_detail("doc-1")
        assert detail.content, "content must be non-empty"

    async def test_citations_are_citation_instances(
        self,
        service: ODLService,
    ) -> None:
        detail = await service.get_document_detail("doc-1")
        assert len(detail.citations) > 0
        for c in detail.citations:
            assert isinstance(c, Citation)

    async def test_toc_is_list_of_toc_nodes(
        self,
        service: ODLService,
    ) -> None:
        detail = await service.get_document_detail("doc-1")
        assert len(detail.toc) > 0
        for node in detail.toc:
            assert isinstance(node, TocNode)

    async def test_toc_nodes_have_correct_types(
        self,
        service: ODLService,
    ) -> None:
        detail = await service.get_document_detail("doc-1")
        for node in detail.toc:
            assert isinstance(node.id, str)
            assert isinstance(node.document_id, str)
            assert isinstance(node.title, str)
            assert isinstance(node.parent_id, str)
            assert isinstance(node.level, int)
            assert isinstance(node.child_count, int)

    async def test_unknown_document_raises(self, service: ODLService) -> None:
        with pytest.raises(NotFoundError):
            await service.get_document_detail("nonexistent")

    async def test_tracing_is_called(
        self,
        service: ODLService,
        tracer_mock: MagicMock,
    ) -> None:
        """Verify that get_document_detail calls tracer.trace with correct args."""
        await service.get_document_detail("doc-1")
        tracer_mock.trace.assert_called_once_with(
            "get_document_detail",
            source_id="doc-1",
        )


# -- list_topics ---------------------------------------------------------------


class TestListTopics:
    """list_topics -- content-rich checks."""

    async def test_returns_list_of_topic_nodes(
        self,
        service: ODLService,
    ) -> None:
        topics = await service.list_topics()
        assert len(topics) > 0
        for t in topics:
            assert isinstance(t, TopicNode)

    async def test_topic_fields_have_correct_types(
        self,
        service: ODLService,
    ) -> None:
        topics = await service.list_topics()
        for t in topics:
            assert isinstance(t.id, str)
            assert isinstance(t.name, str)
            assert isinstance(t.parent_id, str)
            assert isinstance(t.description, str | None)
            assert isinstance(t.child_count, int)
            assert isinstance(t.document_count, int)

    async def test_topic_fields_non_empty(self, service: ODLService) -> None:
        topics = await service.list_topics()
        for t in topics:
            assert t.id, "id must be non-empty"
            assert t.name, "name must be non-empty"

    async def test_filter_by_parent_id(self, service: ODLService) -> None:
        """Root topics have parent_id == ''."""
        root_topics = await service.list_topics(parent_id="")
        assert len(root_topics) > 0
        for t in root_topics:
            assert t.parent_id == ""

    async def test_filter_by_query(self, service: ODLService) -> None:
        """Query filters root topics by name."""
        filtered = await service.list_topics(query="рубрик")
        assert len(filtered) > 0
        for t in filtered:
            assert "рубрик" in t.name.lower()

    async def test_filter_by_query_with_parent(
        self,
        service: ODLService,
    ) -> None:
        """Query filters child topics when parent_id is specified."""
        filtered = await service.list_topics(parent_id="topic-root", query="налог")
        assert len(filtered) > 0
        for t in filtered:
            assert "налог" in t.name.lower()

    async def test_query_no_match_returns_empty(
        self,
        service: ODLService,
    ) -> None:
        filtered = await service.list_topics(query="xyznonexistent")
        assert len(filtered) == 0

    async def test_tracing_is_called(
        self,
        service: ODLService,
        tracer_mock: MagicMock,
    ) -> None:
        """Verify that list_topics calls tracer.trace with correct args."""
        await service.list_topics(parent_id="topic-root", query="налог")
        tracer_mock.trace.assert_called_once_with(
            "list_topics",
            parent_id="topic-root",
        )


# -- get_toc -------------------------------------------------------------------


class TestGetToc:
    """get_toc -- content-rich checks."""

    async def test_returns_list_of_toc_nodes(
        self,
        service: ODLService,
    ) -> None:
        toc = await service.get_toc(document_id="doc-1")
        assert len(toc) > 0
        for node in toc:
            assert isinstance(node, TocNode)

    async def test_toc_fields_have_correct_types(
        self,
        service: ODLService,
    ) -> None:
        toc = await service.get_toc(document_id="doc-1")
        for node in toc:
            assert isinstance(node.id, str)
            assert isinstance(node.document_id, str)
            assert isinstance(node.title, str)
            assert isinstance(node.parent_id, str)
            assert isinstance(node.level, int)
            assert isinstance(node.child_count, int)

    async def test_toc_fields_non_empty(self, service: ODLService) -> None:
        toc = await service.get_toc(document_id="doc-1")
        for node in toc:
            assert node.id, "id must be non-empty"
            assert node.document_id, "document_id must be non-empty"
            assert node.title, "title must be non-empty"

    async def test_filter_by_parent_section(
        self,
        service: ODLService,
    ) -> None:
        """Root sections have parent_id == ''."""
        root = await service.get_toc(document_id="doc-1", parent_section_id="")
        assert len(root) > 0
        for node in root:
            assert node.parent_id == ""

    async def test_default_returns_root_sections(
        self,
        service: ODLService,
    ) -> None:
        """When parent_section_id is None, returns only root sections."""
        toc = await service.get_toc(document_id="doc-1")
        assert len(toc) > 0
        for node in toc:
            assert node.parent_id == "", (
                f"Expected root section (parent_id=''), got parent_id='{node.parent_id}'"
            )

    async def test_filter_by_query(self, service: ODLService) -> None:
        """Query filters root sections by title."""
        filtered = await service.get_toc(document_id="doc-1", query="глава")
        assert len(filtered) > 0
        for node in filtered:
            assert "глава" in node.title.lower()

    async def test_filter_by_query_with_parent(
        self,
        service: ODLService,
    ) -> None:
        """Query filters child sections when parent_section_id is specified."""
        filtered = await service.get_toc(
            document_id="doc-1",
            parent_section_id="sec-1",
            query="статья",
        )
        assert len(filtered) > 0
        for node in filtered:
            assert "статья" in node.title.lower()

    async def test_unknown_document_raises_not_found(
        self,
        service: ODLService,
    ) -> None:
        """Unknown document should raise NotFoundError per Protocol contract."""
        with pytest.raises(NotFoundError):
            await service.get_toc(document_id="nonexistent")

    async def test_tracing_is_called(
        self,
        service: ODLService,
        tracer_mock: MagicMock,
    ) -> None:
        """Verify that get_toc calls tracer.trace with correct args."""
        await service.get_toc(document_id="doc-1", parent_section_id="sec-1")
        tracer_mock.trace.assert_called_once_with(
            "get_toc",
            document_id="doc-1",
        )
