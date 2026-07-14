"""Unit tests for MCP API server (core/api/mcp_server.py).

Tests cover:
- create_mcp_server returns a FastMCP instance with correct metadata
- search_documents tool — success, validation, error mapping
- get_document_detail tool — success, 404, 503
- list_topics tool — success, 404
- get_toc tool — success, 404
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.api.mcp_server import create_mcp_server
from core.errors import InvalidInputError, NotFoundError, SourceUnavailableError
from core.models.models import (
    ConfidenceSignals,
    DocumentDetail,
    LegalStatus,
    SearchContext,
    SearchResponse,
    SearchResult,
    SourceAvailability,
    TocNode,
    TopicNode,
)


@pytest.fixture
def mock_service() -> MagicMock:
    """Create a mock ODLServiceProtocol with all methods as AsyncMock."""
    svc = MagicMock()
    svc.search_documents = AsyncMock()
    svc.get_document_detail = AsyncMock()
    svc.list_topics = AsyncMock()
    svc.get_toc = AsyncMock()
    return svc


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _call_tool(mcp, name: str, **kwargs):
    """Helper to call an MCP tool by name via the tool manager."""
    return await mcp._tool_manager.call_tool(name, kwargs)


# ------------------------------------------------------------------
# create_mcp_server
# ------------------------------------------------------------------


class TestCreateMCPServer:
    """Tests for create_mcp_server factory."""

    def test_returns_fastmcp_instance(self, mock_service: MagicMock) -> None:
        """create_mcp_server returns a FastMCP instance."""
        mcp = create_mcp_server(mock_service)
        assert mcp is not None
        assert mcp.name == "ODL Service"

    def test_tools_are_registered(self, mock_service: MagicMock) -> None:
        """All 4 tools are registered on the FastMCP instance."""
        mcp = create_mcp_server(mock_service)
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        assert tool_names == {
            "search_documents",
            "get_document_detail",
            "list_topics",
            "get_toc",
        }


# ------------------------------------------------------------------
# search_documents
# ------------------------------------------------------------------


class TestSearchDocuments:
    """Tests for the search_documents MCP tool."""

    @pytest.fixture
    def sample_response(self) -> SearchResponse:
        return SearchResponse(
            results=[
                SearchResult(
                    id="doc-1",
                    title="Test Document",
                    snippet="Test snippet",
                    url="http://example.com/doc-1",
                    source_name="Test Source",
                    created_at=_now(),
                    legal_status=LegalStatus.ACTIVE,
                    confidence=ConfidenceSignals(
                        retrieval_relevance=0.95,
                        data_freshness=_now(),
                        source_availability=SourceAvailability.AVAILABLE,
                    ),
                ),
            ],
            total_count=1,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_success(
        self,
        mock_service: MagicMock,
        sample_response: SearchResponse,
    ) -> None:
        """Successful search returns serialized SearchResponse."""
        mock_service.search_documents.return_value = sample_response
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "search_documents", query="test query")

        assert "error" not in result
        assert result["results"][0]["id"] == "doc-1"
        assert result["total_count"] == 1
        mock_service.search_documents.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_search_context(
        self,
        mock_service: MagicMock,
        sample_response: SearchResponse,
    ) -> None:
        """Search context is built from tool parameters and passed to service."""
        mock_service.search_documents.return_value = sample_response
        mcp = create_mcp_server(mock_service)

        await _call_tool(
            mcp,
            "search_documents",
            query="test",
            offset=5,
            max_results=20,
            region="Московская область",
            topic=["taxes"],
            organization=["FNS"],
            official_only=True,
            max_age_days=30,
        )

        _call_args = mock_service.search_documents.await_args
        assert _call_args is not None
        _query, context = _call_args.args
        assert _query == "test"
        assert isinstance(context, SearchContext)
        assert context.offset == 5
        assert context.max_results == 20
        assert context.region == "Московская область"
        assert context.topic == ["taxes"]
        assert context.organization == ["FNS"]
        assert context.official_only is True
        assert context.max_age_days == 30

    @pytest.mark.asyncio
    async def test_invalid_max_results(
        self,
        mock_service: MagicMock,
    ) -> None:
        """max_results outside [1, 50] returns an error dict."""
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "search_documents", query="test", max_results=0)
        assert result["error"] == "max_results must be between 1 and 50"
        assert result["code"] == "INVALID_INPUT"

        result = await _call_tool(mcp, "search_documents", query="test", max_results=51)
        assert result["error"] == "max_results must be between 1 and 50"
        assert result["code"] == "INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_invalid_input_error(
        self,
        mock_service: MagicMock,
    ) -> None:
        """InvalidInputError from service is mapped to error dict."""
        mock_service.search_documents.side_effect = InvalidInputError("bad query")
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "search_documents", query="bad")
        assert result["error"] == "bad query"
        assert result["code"] == "INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_not_found_error(
        self,
        mock_service: MagicMock,
    ) -> None:
        """NotFoundError from service is mapped to error dict."""
        mock_service.search_documents.side_effect = NotFoundError("not found")
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "search_documents", query="missing")
        assert result["error"] == "not found"
        assert result["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_source_unavailable_error(
        self,
        mock_service: MagicMock,
    ) -> None:
        """SourceUnavailableError from service is mapped to error dict."""
        mock_service.search_documents.side_effect = SourceUnavailableError("down")
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "search_documents", query="test")
        assert result["error"] == "down"
        assert result["code"] == "SOURCE_UNAVAILABLE"


# ------------------------------------------------------------------
# get_document_detail
# ------------------------------------------------------------------


class TestGetDocumentDetail:
    """Tests for the get_document_detail MCP tool."""

    @pytest.fixture
    def sample_detail(self) -> DocumentDetail:
        return DocumentDetail(
            id="doc-1",
            title="Test Document",
            url="http://example.com/doc-1",
            source_name="Test Source",
            created_at=_now(),
            legal_status=LegalStatus.ACTIVE,
        )

    @pytest.mark.asyncio
    async def test_success(
        self,
        mock_service: MagicMock,
        sample_detail: DocumentDetail,
    ) -> None:
        """Successful detail fetch returns serialized DocumentDetail."""
        mock_service.get_document_detail.return_value = sample_detail
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "get_document_detail", source_id="doc-1")

        assert "error" not in result
        assert result["id"] == "doc-1"
        assert result["title"] == "Test Document"
        mock_service.get_document_detail.assert_awaited_once_with("doc-1")

    @pytest.mark.asyncio
    async def test_not_found(
        self,
        mock_service: MagicMock,
    ) -> None:
        """NotFoundError returns error dict."""
        mock_service.get_document_detail.side_effect = NotFoundError("doc not found")
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "get_document_detail", source_id="missing")
        assert result["error"] == "doc not found"
        assert result["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_source_unavailable(
        self,
        mock_service: MagicMock,
    ) -> None:
        """SourceUnavailableError returns error dict."""
        mock_service.get_document_detail.side_effect = SourceUnavailableError("source down")
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "get_document_detail", source_id="doc-1")
        assert result["error"] == "source down"
        assert result["code"] == "SOURCE_UNAVAILABLE"


# ------------------------------------------------------------------
# list_topics
# ------------------------------------------------------------------


class TestListTopics:
    """Tests for the list_topics MCP tool."""

    @pytest.fixture
    def sample_topics(self) -> list[TopicNode]:
        return [
            TopicNode(
                id="topic-1",
                name="Налоги",
                parent_id="",
                child_count=3,
            ),
            TopicNode(
                id="topic-2",
                name="Земельное право",
                parent_id="",
                child_count=0,
            ),
        ]

    @pytest.mark.asyncio
    async def test_success(
        self,
        mock_service: MagicMock,
        sample_topics: list[TopicNode],
    ) -> None:
        """Successful list_topics returns results list."""
        mock_service.list_topics.return_value = sample_topics
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "list_topics")

        assert "error" not in result
        assert len(result["results"]) == 2
        assert result["results"][0]["name"] == "Налоги"
        mock_service.list_topics.assert_awaited_once_with(parent_id=None, query="")

    @pytest.mark.asyncio
    async def test_with_parent_and_query(
        self,
        mock_service: MagicMock,
        sample_topics: list[TopicNode],
    ) -> None:
        """parent_id and query are passed through."""
        mock_service.list_topics.return_value = sample_topics
        mcp = create_mcp_server(mock_service)

        await _call_tool(mcp, "list_topics", parent_id="topic-1", query="налог")

        mock_service.list_topics.assert_awaited_once_with(parent_id="topic-1", query="налог")

    @pytest.mark.asyncio
    async def test_not_found(
        self,
        mock_service: MagicMock,
    ) -> None:
        """NotFoundError returns error dict."""
        mock_service.list_topics.side_effect = NotFoundError("topic not found")
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "list_topics", parent_id="invalid")
        assert result["error"] == "topic not found"
        assert result["code"] == "NOT_FOUND"


# ------------------------------------------------------------------
# get_toc
# ------------------------------------------------------------------


class TestGetToc:
    """Tests for the get_toc MCP tool."""

    @pytest.fixture
    def sample_toc(self) -> list[TocNode]:
        return [
            TocNode(
                id="sec-1",
                document_id="doc-1",
                title="Глава 1. Общие положения",
                parent_id="",
                level=0,
                child_count=5,
            ),
            TocNode(
                id="sec-2",
                document_id="doc-1",
                title="Глава 2. Основные права",
                parent_id="",
                level=0,
                child_count=3,
            ),
        ]

    @pytest.mark.asyncio
    async def test_success(
        self,
        mock_service: MagicMock,
        sample_toc: list[TocNode],
    ) -> None:
        """Successful get_toc returns results list."""
        mock_service.get_toc.return_value = sample_toc
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(mcp, "get_toc", document_id="doc-1")

        assert "error" not in result
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "Глава 1. Общие положения"
        mock_service.get_toc.assert_awaited_once_with(
            document_id="doc-1",
            parent_section_id=None,
            query="",
        )

    @pytest.mark.asyncio
    async def test_with_parent_and_query(
        self,
        mock_service: MagicMock,
        sample_toc: list[TocNode],
    ) -> None:
        """parent_section_id and query are passed through."""
        mock_service.get_toc.return_value = sample_toc
        mcp = create_mcp_server(mock_service)

        await _call_tool(
            mcp,
            "get_toc",
            document_id="doc-1",
            parent_section_id="sec-1",
            query="права",
        )

        mock_service.get_toc.assert_awaited_once_with(
            document_id="doc-1",
            parent_section_id="sec-1",
            query="права",
        )

    @pytest.mark.asyncio
    async def test_not_found(
        self,
        mock_service: MagicMock,
    ) -> None:
        """NotFoundError returns error dict."""
        mock_service.get_toc.side_effect = NotFoundError("section not found")
        mcp = create_mcp_server(mock_service)

        result = await _call_tool(
            mcp,
            "get_toc",
            document_id="doc-1",
            parent_section_id="invalid",
        )
        assert result["error"] == "section not found"
        assert result["code"] == "NOT_FOUND"
