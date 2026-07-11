"""MCP API server — thin adapter over ODLServiceProtocol.

Provides MCP tools for AI agents.
Each tool is a thin wrapper around an ODLServiceProtocol method.

Tools:
- search_documents — search documents by query
- get_document_detail — full document card
- list_topics — hierarchical rubricator
- get_toc — document table of contents
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

from core.errors import InvalidInputError, NotFoundError, SourceUnavailableError
from core.models.models import SearchContext

if TYPE_CHECKING:
    from core.odl_service_protocol import ODLServiceProtocol


def _error_response(message: str, code: str) -> dict[str, Any]:
    """Return a structured error dict for MCP tool responses."""
    return {"error": message, "code": code}


def create_mcp_server(service: ODLServiceProtocol) -> FastMCP:
    """Create an MCP server with an injected ODLService.

    Args:
        service: ODLServiceProtocol implementation (stub or real service).

    Returns:
        Configured FastMCP server with 4 tools.
    """
    mcp = FastMCP(
        name="ODL Service",
        instructions=(
            "Official Data Layer — a data access layer for AI agents. "
            "Provides access to government and social documents "
            "from official sources."
        ),
    )

    # ------------------------------------------------------------------
    # search_documents
    # ------------------------------------------------------------------
    @mcp.tool(
        name="search_documents",
        description=(
            "Search official documents by text query. "
            "Returns results with metadata, confidence signals, "
            "and pagination information."
        ),
    )
    async def search_documents(
        query: str,
        offset: int = 0,
        max_results: int = 10,
        region: str | None = None,
        topic: list[str] | None = None,
        organization: list[str] | None = None,
        official_only: bool = False,
        max_age_days: int | None = None,
    ) -> dict[str, Any]:
        """Search documents by query.

        Args:
            query: Free-text user question/intent.
            offset: Pagination offset.
            max_results: Maximum number of results (1-50).
            region: Region filter.
            topic: Topic rubric filter (e.g. ["taxes", "property"]).
            organization: Organization filter (e.g. ["FNS", "Ministry of Justice"]).
            official_only: Only official sources.
            max_age_days: Maximum document age in days.

        Returns:
            SearchResponse as dict (mode="json").
        """
        if not (1 <= max_results <= 50):
            return _error_response("max_results must be between 1 and 50", "INVALID_INPUT")
        context = SearchContext(
            offset=offset,
            max_results=max_results,
            region=region,
            topic=topic,
            organization=organization,
            official_only=official_only,
            max_age_days=max_age_days,
        )
        try:
            response = await service.search_documents(query, context)
            return response.model_dump(mode="json")
        except InvalidInputError as e:
            return _error_response(str(e), "INVALID_INPUT")
        except NotFoundError as e:
            return _error_response(str(e), "NOT_FOUND")
        except SourceUnavailableError as e:
            return _error_response(str(e), "SOURCE_UNAVAILABLE")

    # ------------------------------------------------------------------
    # get_document_detail
    # ------------------------------------------------------------------
    @mcp.tool(
        name="get_document_detail",
        description=(
            "Get the full document card by its source_id. "
            "Contains the full text, citations with section references, "
            "and table of contents."
        ),
    )
    async def get_document_detail(
        source_id: str,
    ) -> dict[str, Any]:
        """Full document card.

        Args:
            source_id: Document identifier in the source.

        Returns:
            DocumentDetail as dict (mode="json").
        """
        try:
            detail = await service.get_document_detail(source_id)
            return detail.model_dump(mode="json")
        except NotFoundError as e:
            return _error_response(str(e), "NOT_FOUND")
        except SourceUnavailableError as e:
            return _error_response(str(e), "SOURCE_UNAVAILABLE")

    # ------------------------------------------------------------------
    # list_topics
    # ------------------------------------------------------------------
    @mcp.tool(
        name="list_topics",
        description=(
            "Browse the hierarchical rubricator. "
            "Calling without parent_id returns root rubrics. "
            "Can be filtered by text query."
        ),
    )
    async def list_topics(
        parent_id: str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        """Browse the rubricator.

        Args:
            parent_id: Parent rubric ID. None = root rubrics.
            query: Optional search query to filter rubrics.

        Returns:
            Dict with "results" key containing list of TopicNode as dict (mode="json"),
            or an error dict on failure.
        """
        try:
            topics = await service.list_topics(parent_id=parent_id, query=query)
            return {"results": [t.model_dump(mode="json") for t in topics]}
        except NotFoundError as e:
            return _error_response(str(e), "NOT_FOUND")
        except SourceUnavailableError as e:
            return _error_response(str(e), "SOURCE_UNAVAILABLE")

    # ------------------------------------------------------------------
    # get_toc
    # ------------------------------------------------------------------
    @mcp.tool(
        name="get_toc",
        description=(
            "Get the table of contents of a document. "
            "Calling without parent_section_id returns root sections. "
            "Can be filtered by text query."
        ),
    )
    async def get_toc(
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        """Document table of contents.

        Args:
            document_id: Document ID.
            parent_section_id: Parent section ID. None = root sections.
            query: Optional search query to filter sections.

        Returns:
            Dict with "results" key containing list of TocNode as dict (mode="json"),
            or an error dict on failure.
        """
        try:
            toc = await service.get_toc(
                document_id=document_id,
                parent_section_id=parent_section_id,
                query=query,
            )
            return {"results": [t.model_dump(mode="json") for t in toc]}
        except NotFoundError as e:
            return _error_response(str(e), "NOT_FOUND")
        except SourceUnavailableError as e:
            return _error_response(str(e), "SOURCE_UNAVAILABLE")

    return mcp


__all__ = [
    "create_mcp_server",
]
