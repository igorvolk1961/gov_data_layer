"""Tests for ODLService — content-rich checks on field types and non-emptiness."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.errors import NotFoundError
from core.index.qdrant_store import QdrantStore
from core.ingest.embedder import Embedder
from core.models.models import (
    Citation,
    ConfidenceSignals,
    DocumentChunk,
    DocumentDetail,
    LegalStatus,
    OfficialDocument,
    SearchContext,
    SearchResponse,
    SearchResult,
    Source,
    SourceAvailability,
    TocNode,
    TopicNode,
)
from core.odl_service import ODLService


@pytest.fixture
def doc_repo_mock() -> MagicMock:
    """Mock DocumentRepository returning a sample OfficialDocument."""
    mock = MagicMock()
    doc = OfficialDocument(
        id="stub-doc-001",
        title="Test Document Title",
        url="https://example.com/doc-1",
        source=Source(id="stub", name="Stub Source", url="https://example.com"),
        summary="Test summary",
        document_number="doc-1",
    )

    # get_document_by_id — kept for get_toc which uses UUID lookup
    async def _get_by_id(doc_id: str) -> OfficialDocument | None:
        return doc if doc_id in ("doc-1", "stub-doc-001") else None

    mock.get_document_by_id = AsyncMock(side_effect=_get_by_id)

    # get_document_by_publish_id — used by get_document_detail
    # The compound ID "doc-1" is parsed as source_id="doc", publish_id="1"
    async def _get_by_publish_id(publish_id: str) -> OfficialDocument | None:
        return doc if publish_id in ("1", "stub-doc-001") else None

    mock.get_document_by_publish_id = AsyncMock(side_effect=_get_by_publish_id)

    # get_document_uuid — used by get_document_detail for TOC lookup
    async def _get_uuid(publish_id: str) -> str | None:
        return "stub-doc-001" if publish_id == "1" else None

    mock.get_document_uuid = AsyncMock(side_effect=_get_uuid)
    return mock


@pytest.fixture
def ref_repo_mock() -> MagicMock:
    """Mock ReferenceRepository returning sample topics."""
    from core.models.models import TopicNode

    mock = MagicMock()
    topic = TopicNode(id="topic-1", name="Рубрика 1", parent_id="")

    async def _list_topics(**kwargs: object) -> list[TopicNode]:
        query = str(kwargs.get("query", ""))
        if query and query.lower() not in topic.name.lower():
            return []
        # parent_id is passed through — mock returns data for any parent_id
        return [topic]

    mock.list_topics = AsyncMock(side_effect=_list_topics)
    return mock


@pytest.fixture
def section_repo_mock() -> MagicMock:
    """Mock SectionRepository returning sample TOC."""
    from core.models.models import TocNode

    mock = MagicMock()
    toc_node = TocNode(
        id="sec-1",
        document_id="doc-1",
        title="Глава 1 — Основные положения",
        parent_id="",
        level=0,
        child_count=0,
    )
    child_node = TocNode(
        id="sec-1-1",
        document_id="doc-1",
        title="Статья 1",
        parent_id="sec-1",
        level=1,
        child_count=0,
    )

    async def _get_toc(document_uuid: str, parent_section_id: str | None = None) -> list[TocNode]:
        if parent_section_id == "sec-1":
            return [child_node]  # return children for known parent
        if parent_section_id:
            return []
        return [toc_node] if document_uuid in ("doc-1", "stub-doc-001") else []

    mock.get_toc = AsyncMock(side_effect=_get_toc)

    # get_sections — used by get_document_detail when query is not provided
    async def _get_sections(document_uuid: str) -> list[TocNode]:
        return [toc_node, child_node] if document_uuid in ("doc-1", "stub-doc-001") else []

    mock.get_sections = AsyncMock(side_effect=_get_sections)
    return mock


@pytest.fixture
def tracer_mock() -> MagicMock:
    """Create a no-op tracer mock for injection into ODLService."""
    span_mock = MagicMock()
    span_mock.__enter__.return_value = span_mock
    tracer = MagicMock()
    tracer.trace.return_value = span_mock
    return tracer


@pytest.fixture
def qdrant_mock() -> MagicMock:
    """Mock QdrantStore that returns sample chunks."""
    mock = MagicMock(spec=QdrantStore)
    chunk = DocumentChunk(
        id="chunk-001",
        document_id="stub-doc-001",
        doc_uuid="uuid-001",
        text="Test document about НПА regulations and legal framework. "
        "This is a sample document for testing search functionality.",
        section_path=["Section 1"],
        chunk_index=0,
        data_freshness=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    mock.build_filter = AsyncMock(return_value=None)
    mock.search = AsyncMock(return_value=[(chunk, 0.95)])
    return mock


@pytest.fixture
def embedder_mock() -> MagicMock:
    """Mock Embedder that returns a fixed vector."""
    mock = MagicMock(spec=Embedder)
    mock.embed_query = AsyncMock(return_value=[0.1] * 384)
    return mock


@pytest.fixture
def service(tracer_mock: MagicMock) -> ODLService:
    """ODLService with StubAdapter and a no-op tracer (no Qdrant)."""
    return ODLService(tracer=tracer_mock)


@pytest.fixture
def qdrant_service(
    tracer_mock: MagicMock,
    qdrant_mock: MagicMock,
    embedder_mock: MagicMock,
) -> ODLService:
    """ODLService with Qdrant + Embedder mocks for testing search pipeline."""
    return ODLService(
        tracer=tracer_mock,
        qdrant=qdrant_mock,
        embedder=embedder_mock,
    )


# -- search_documents ----------------------------------------------------------


class TestSearchDocumentsWithoutQdrant:
    """search_documents without Qdrant configured — returns empty results."""

    pytestmark = pytest.mark.asyncio

    async def test_returns_search_response(self, service: ODLService) -> None:
        response = await service.search_documents("тест")
        assert isinstance(response, SearchResponse)

    async def test_no_qdrant_returns_empty(self, service: ODLService) -> None:
        response = await service.search_documents("тест")
        assert len(response.results) == 0
        assert response.total_count == 0

    async def test_offset_from_context(self, service: ODLService) -> None:
        ctx = SearchContext(offset=5)
        response = await service.search_documents("тест", context=ctx)
        assert response.offset == 5

    async def test_tracing_is_called(
        self,
        service: ODLService,
        tracer_mock: MagicMock,
    ) -> None:
        await service.search_documents("тест")
        tracer_mock.trace.assert_called_once_with(
            "search_documents",
            query="тест",
        )


class TestSearchDocumentsWithQdrant:
    """search_documents with Qdrant mock — tests the Qdrant search pipeline."""

    pytestmark = pytest.mark.asyncio

    async def test_returns_search_response(
        self,
        qdrant_service: ODLService,
    ) -> None:
        response = await qdrant_service.search_documents("тест")
        assert isinstance(response, SearchResponse)

    async def test_results_from_qdrant(
        self,
        qdrant_service: ODLService,
    ) -> None:
        response = await qdrant_service.search_documents("тест")
        assert len(response.results) > 0
        for r in response.results:
            assert isinstance(r, SearchResult)

    async def test_result_fields_from_chunk(
        self,
        qdrant_service: ODLService,
    ) -> None:
        response = await qdrant_service.search_documents("тест")
        for r in response.results:
            assert r.id == "stub-doc-001"
            assert r.title, "title must be non-empty"
            assert r.snippet, "snippet must be non-empty"

    async def test_confidence_signals(
        self,
        qdrant_service: ODLService,
    ) -> None:
        response = await qdrant_service.search_documents("тест")
        for r in response.results:
            assert isinstance(r.confidence, ConfidenceSignals)
            assert 0.0 <= r.confidence.retrieval_relevance <= 1.0
            assert r.confidence.data_freshness is not None
            assert r.confidence.data_freshness.year == 2024
            assert r.confidence.source_availability == SourceAvailability.AVAILABLE

    async def test_total_count_matches_results_length(
        self,
        qdrant_service: ODLService,
    ) -> None:
        response = await qdrant_service.search_documents("тест")
        assert response.total_count == len(response.results)

    async def test_build_filter_called(
        self,
        qdrant_service: ODLService,
        qdrant_mock: MagicMock,
    ) -> None:
        """search() now calls build_filter() internally — verify search is called without explicit filters."""
        await qdrant_service.search_documents("тест")
        qdrant_mock.search.assert_awaited_once()

    async def test_embedder_called(
        self,
        qdrant_service: ODLService,
        embedder_mock: MagicMock,
    ) -> None:
        await qdrant_service.search_documents("тест")
        embedder_mock.embed_query.assert_awaited_once_with("тест")

    async def test_offset_passthrough(
        self,
        qdrant_service: ODLService,
    ) -> None:
        ctx = SearchContext(offset=1)
        response = await qdrant_service.search_documents("тест", context=ctx)
        assert response.offset == 1


# -- get_document_detail -------------------------------------------------------


class TestGetDocumentDetail:
    """get_document_detail -- content-rich checks."""

    pytestmark = pytest.mark.asyncio

    @pytest.fixture(autouse=True)
    def _setup_repos(
        self, service: ODLService, doc_repo_mock: MagicMock, section_repo_mock: MagicMock
    ) -> None:
        service._doc_repo = doc_repo_mock
        service._section_repo = section_repo_mock

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

    async def test_citations_and_toc_are_present(self, service: ODLService) -> None:
        detail = await service.get_document_detail("doc-1")
        assert isinstance(detail.citations, list)
        assert isinstance(detail.toc, list)

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
        tracer_mock.trace.assert_any_call(
            "get_document_detail",
            source_id="doc-1",
        )


class TestGetDocumentDetailWithQdrant:
    """get_document_detail with Qdrant mock — citations from chunks."""

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def detail_qdrant_mock(self) -> MagicMock:
        """Mock QdrantStore that returns sample chunks for a document."""
        mock = MagicMock(spec=QdrantStore)
        mock.get_chunks_by_document_id = AsyncMock(
            return_value=[
                DocumentChunk(
                    id="chunk-001",
                    document_id="stub-doc-001",
                    doc_uuid="uuid-001",
                    text="Текст первого раздела. Часть первая.",
                    section_path=["Раздел I"],
                    chunk_index=0,
                    section_chunk_index=0,
                ),
                DocumentChunk(
                    id="chunk-002",
                    document_id="stub-doc-001",
                    doc_uuid="uuid-001",
                    text="Текст первого раздела. Часть вторая.",
                    section_path=["Раздел I"],
                    chunk_index=1,
                    section_chunk_index=1,
                ),
                DocumentChunk(
                    id="chunk-003",
                    document_id="stub-doc-001",
                    doc_uuid="uuid-001",
                    text="Текст второго раздела.",
                    section_path=["Раздел II"],
                    chunk_index=2,
                    section_chunk_index=0,
                ),
            ],
        )
        return mock

    @pytest.fixture
    def detail_service(
        self,
        tracer_mock: MagicMock,
        detail_qdrant_mock: MagicMock,
        doc_repo_mock: MagicMock,
        section_repo_mock: MagicMock,
    ) -> ODLService:
        """ODLService with Qdrant mock for detail testing."""
        svc = ODLService(
            tracer=tracer_mock,
            qdrant=detail_qdrant_mock,
        )
        svc._doc_repo = doc_repo_mock
        svc._section_repo = section_repo_mock
        return svc

    async def test_citations_from_qdrant_chunks(
        self,
        detail_service: ODLService,
    ) -> None:
        """Citations should come from Qdrant chunks, grouped by section."""
        detail = await detail_service.get_document_detail("doc-1")
        assert len(detail.citations) == 2  # Two unique sections

    async def test_citations_have_section_path(
        self,
        detail_service: ODLService,
    ) -> None:
        """Each citation should have section path from chunks."""
        detail = await detail_service.get_document_detail("doc-1")
        sections = {tuple(c.section) for c in detail.citations if c.section}
        assert ("Раздел I",) in sections
        assert ("Раздел II",) in sections

    async def test_citation_text_merged_with_overlap(
        self,
        detail_service: ODLService,
    ) -> None:
        """Chunks from same section should be merged into one citation text."""
        detail = await detail_service.get_document_detail("doc-1")
        section1_citations = [c for c in detail.citations if c.section == ["Раздел I"]]
        assert len(section1_citations) == 1
        merged = section1_citations[0].text
        assert "Текст первого раздела. Часть первая." in merged
        assert "Текст первого раздела. Часть вторая." in merged

    async def test_detail_still_returns_metadata(
        self,
        detail_service: ODLService,
    ) -> None:
        """Metadata fields should still be present with Qdrant."""
        detail = await detail_service.get_document_detail("doc-1")
        assert detail.id, "id must be non-empty"
        assert detail.title, "title must be non-empty"
        assert detail.url, "url must be non-empty"
        assert detail.source_name, "source_name must be non-empty"
        assert isinstance(detail.toc, list)
        assert len(detail.toc) > 0

    async def test_get_chunks_by_document_id_called(
        self,
        detail_service: ODLService,
        detail_qdrant_mock: MagicMock,
    ) -> None:
        """Verify get_chunks_by_document_id was called with correct doc id."""
        await detail_service.get_document_detail("doc-1")
        # Now uses doc_repo_mock which returns document with id="stub-doc-001"
        detail_qdrant_mock.get_chunks_by_document_id.assert_awaited_once()


class TestGetDocumentDetailQdrantFallback:
    """get_document_detail fallback when Qdrant is unavailable or errors."""

    pytestmark = pytest.mark.asyncio

    @pytest.fixture(autouse=True)
    def _setup_repos(self, doc_repo_mock: MagicMock, section_repo_mock: MagicMock) -> None:
        self._doc_repo = doc_repo_mock
        self._section_repo = section_repo_mock

    @pytest.fixture
    def error_qdrant_mock(self) -> MagicMock:
        """Mock QdrantStore that raises an exception on get_chunks_by_document_id."""
        mock = MagicMock(spec=QdrantStore)
        mock.get_chunks_by_document_id = AsyncMock(
            side_effect=RuntimeError("Qdrant connection failed"),
        )
        return mock

    @pytest.fixture
    def error_service(
        self,
        tracer_mock: MagicMock,
        error_qdrant_mock: MagicMock,
    ) -> ODLService:
        svc = ODLService(tracer=tracer_mock, qdrant=error_qdrant_mock)
        svc._doc_repo = self._doc_repo
        svc._section_repo = self._section_repo
        return svc

    async def test_qdrant_error_falls_back_to_summary(
        self,
        error_service: ODLService,
    ) -> None:
        """When Qdrant errors, citation should come from summary/title."""
        detail = await error_service.get_document_detail("doc-1")
        assert len(detail.citations) == 1
        assert detail.citations[0].text  # non-empty fallback text

    async def test_qdrant_error_still_returns_metadata(
        self,
        error_service: ODLService,
    ) -> None:
        """Metadata should still be present even if Qdrant errors."""
        detail = await error_service.get_document_detail("doc-1")
        assert detail.id, "id must be non-empty"
        assert detail.title, "title must be non-empty"

    @pytest.fixture
    def no_qdrant_service(self, tracer_mock: MagicMock) -> ODLService:
        """ODLService without Qdrant, with mock repos."""
        svc = ODLService(tracer=tracer_mock)
        svc._doc_repo = self._doc_repo
        svc._section_repo = self._section_repo
        return svc

    async def test_no_qdrant_configured_falls_back_to_summary(
        self,
        no_qdrant_service: ODLService,
    ) -> None:
        """Without Qdrant configured, citation is from summary."""
        detail = await no_qdrant_service.get_document_detail("doc-1")
        assert len(detail.citations) == 1
        assert detail.citations[0].text  # non-empty fallback text


class TestMergeOverlappingChunks:
    """Static _merge_overlapping_chunks method."""

    def test_single_chunk(self) -> None:
        chunks = [
            DocumentChunk(
                id="c1",
                document_id="d1",
                doc_uuid="u1",
                text="Single chunk text",
                section_path=["Sec 1"],
                chunk_index=0,
                section_chunk_index=0,
            )
        ]
        result = ODLService._merge_overlapping_chunks(chunks)
        assert result == "Single chunk text"

    def test_empty_list(self) -> None:
        result = ODLService._merge_overlapping_chunks([])
        assert result == ""

    def test_no_overlap_joins_with_newline(self) -> None:
        chunks = [
            DocumentChunk(
                id="c1",
                document_id="d1",
                doc_uuid="u1",
                text="First chunk text.",
                section_path=["Sec 1"],
                chunk_index=0,
                section_chunk_index=0,
            ),
            DocumentChunk(
                id="c2",
                document_id="d1",
                doc_uuid="u1",
                text="Second chunk text.",
                section_path=["Sec 1"],
                chunk_index=1,
                section_chunk_index=1,
            ),
        ]
        result = ODLService._merge_overlapping_chunks(chunks)
        assert "First chunk text." in result
        assert "Second chunk text." in result
        assert "\n\n" in result

    def test_overlap_is_trimmed(self) -> None:
        """When chunks have ≥50 chars overlap, duplicate is removed."""
        overlap = "x" * 60
        chunks = [
            DocumentChunk(
                id="c1",
                document_id="d1",
                doc_uuid="u1",
                text="Prefix." + overlap,
                section_path=["Sec 1"],
                chunk_index=0,
                section_chunk_index=0,
            ),
            DocumentChunk(
                id="c2",
                document_id="d1",
                doc_uuid="u1",
                text=overlap + ".Suffix",
                section_path=["Sec 1"],
                chunk_index=1,
                section_chunk_index=1,
            ),
        ]
        result = ODLService._merge_overlapping_chunks(chunks)
        assert result == "Prefix." + overlap + ".Suffix"
        assert result.count(overlap) == 1  # overlap appears only once

    def test_short_overlap_not_trimmed(self) -> None:
        """Less than 50 chars overlap is not considered intentional."""
        overlap = "x" * 30
        chunks = [
            DocumentChunk(
                id="c1",
                document_id="d1",
                doc_uuid="u1",
                text="A" + overlap,
                section_path=["Sec 1"],
                chunk_index=0,
                section_chunk_index=0,
            ),
            DocumentChunk(
                id="c2",
                document_id="d1",
                doc_uuid="u1",
                text=overlap + "B",
                section_path=["Sec 1"],
                chunk_index=1,
                section_chunk_index=1,
            ),
        ]
        result = ODLService._merge_overlapping_chunks(chunks)
        # Short overlap won't be trimmed — text will be joined with \n\n
        assert result.count(overlap) == 2
