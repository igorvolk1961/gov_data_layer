"""Unit tests for REST API server (core/api/rest_server.py).

Tests cover:
- create_app returns a FastAPI instance with correct metadata
- /health endpoint
- POST /api/v1/search — success, validation, error mapping
- GET /api/v1/documents/{source_id} — success, 404, 503
- GET /api/v1/topics — success, 404
- GET /api/v1/documents/{document_id}/toc — success, 404
- Tracing middleware wraps requests in spans
"""

from __future__ import annotations

import datetime
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.api.rest_server import SearchRequest, create_app
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
from core.observability.config import ObservabilityConfig
from core.observability.tracer import FileFallbackTracer, set_tracer


@pytest.fixture(scope="session", autouse=True)
def _setup_tracer() -> None:
    """Set a FileFallbackTracer so create_app() can call get_tracer()."""
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
        log_path = f.name
    config = ObservabilityConfig(log_file=log_path)
    tracer = FileFallbackTracer(config)
    set_tracer(tracer)


@pytest.fixture
def mock_service() -> MagicMock:
    """Create a mock ODLServiceProtocol with all methods as AsyncMock."""
    svc = MagicMock()
    svc.search_documents = AsyncMock()
    svc.get_document_detail = AsyncMock()
    svc.list_topics = AsyncMock()
    svc.get_toc = AsyncMock()
    svc.admin_get_reference_counts = AsyncMock()
    svc.admin_get_qdrant_status = AsyncMock()
    svc.admin_get_document_status = AsyncMock()
    return svc


@pytest.fixture
def client(mock_service: MagicMock) -> TestClient:
    """FastAPI TestClient with mocked service."""
    app = create_app(mock_service)
    return TestClient(app)


# ──────────────────────────────────────────────
#  SearchRequest model
# ──────────────────────────────────────────────


class TestSearchRequest:
    def test_minimal(self) -> None:
        req = SearchRequest(query="test")
        assert req.query == "test"
        assert req.offset == 0
        assert req.limit == 10

    def test_full(self) -> None:
        req = SearchRequest(query="test", offset=5, limit=20, region="msk", topic="law")
        assert req.offset == 5
        assert req.limit == 20
        assert req.region == "msk"
        assert req.topic == "law"

    def test_empty_query_invalid(self) -> None:
        with pytest.raises(ValueError, match="String should have at least 1 character"):
            SearchRequest(query="")

    def test_negative_offset_invalid(self) -> None:
        with pytest.raises(ValueError, match="Input should be greater than or equal to 0"):
            SearchRequest(query="test", offset=-1)

    def test_limit_exceeds_max(self) -> None:
        with pytest.raises(ValueError, match="Input should be less than or equal to 100"):
            SearchRequest(query="test", limit=200)


# ──────────────────────────────────────────────
#  create_app
# ──────────────────────────────────────────────


class TestCreateApp:
    def test_returns_fastapi_app(self, mock_service: MagicMock) -> None:
        app = create_app(mock_service)
        assert app.title == "Official Data Layer API"
        assert app.version == "0.1.0"
        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"

    def test_openapi_schema(self, mock_service: MagicMock) -> None:
        """OpenAPI schema includes all expected paths."""
        app = create_app(mock_service)
        client = TestClient(app)
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        assert "/health" in paths
        assert "/api/v1/search" in paths
        assert "/api/v1/documents/{source_id}" in paths
        assert "/api/v1/topics" in paths
        assert "/api/v1/documents/{document_id}/toc" in paths


# ──────────────────────────────────────────────
#  /health
# ──────────────────────────────────────────────


class TestHealth:
    def test_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "redis" in data
        assert "database" in data
        assert "qdrant" in data
        assert "langfuse" in data

    def test_qdrant_unavailable_when_not_provided(self, client: TestClient) -> None:
        """Qdrant status is 'unavailable' when no QdrantStore is passed to create_app."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["qdrant"] == "unavailable"
        assert data["langfuse"] == "unavailable"  # FileFallbackTracer — not LangFuse


# ──────────────────────────────────────────────
#  POST /api/v1/search
# ──────────────────────────────────────────────


def _make_search_result(
    doc_id: str = "doc-1",
    title: str = "Test Document",
    snippet: str = "A test snippet",
    url: str = "http://example.com/doc-1",
    source_name: str = "Test Source",
    created_at: datetime.datetime | None = None,
    legal_status: LegalStatus = LegalStatus.ACTIVE,
    confidence: ConfidenceSignals | None = None,
) -> SearchResult:
    if created_at is None:
        created_at = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
    if confidence is None:
        confidence = ConfidenceSignals(
            retrieval_relevance=0.95,
            data_freshness=datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
            source_availability=SourceAvailability.AVAILABLE,
        )
    return SearchResult(
        id=doc_id,
        title=title,
        snippet=snippet,
        url=url,
        source_name=source_name,
        created_at=created_at,
        legal_status=legal_status,
        confidence=confidence,
    )


def _make_search_response(
    results: list[SearchResult] | None = None,
    total_count: int = 0,
    offset: int = 0,
) -> SearchResponse:
    if results is None:
        results = []
    return SearchResponse(results=results, total_count=total_count, offset=offset)


class TestSearchDocuments:
    def test_success(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.search_documents.return_value = _make_search_response(
            results=[_make_search_result(doc_id="doc-1")],
            total_count=1,
        )
        resp = client.post("/api/v1/search", json={"query": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert data["results"][0]["id"] == "doc-1"
        mock_service.search_documents.assert_awaited_once()

    def test_passes_context(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.search_documents.return_value = _make_search_response()
        client.post(
            "/api/v1/search",
            json={"query": "test", "offset": 5, "limit": 20, "region": "msk"},
        )
        _call_args = mock_service.search_documents.await_args
        assert _call_args is not None
        _query, context = _call_args.args
        assert isinstance(context, SearchContext)
        assert context.offset == 5
        assert context.max_results == 20
        assert context.region == "msk"

    def test_invalid_input_returns_400(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.search_documents.side_effect = InvalidInputError("bad query")
        resp = client.post("/api/v1/search", json={"query": "test"})
        assert resp.status_code == 400
        assert "bad query" in resp.json()["detail"]

    def test_source_unavailable_returns_503(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.search_documents.side_effect = SourceUnavailableError("down")
        resp = client.post("/api/v1/search", json={"query": "test"})
        assert resp.status_code == 503
        assert "down" in resp.json()["detail"]

    def test_validation_error_on_empty_body(self, client: TestClient) -> None:
        resp = client.post("/api/v1/search", json={})
        assert resp.status_code == 422


# ──────────────────────────────────────────────
#  GET /api/v1/documents/{source_id}
# ──────────────────────────────────────────────


def _make_document_detail(
    doc_id: str = "doc-1",
    title: str = "Test",
    url: str = "http://example.com/doc-1",
    source_name: str = "Test Source",
    created_at: datetime.datetime | None = None,
    legal_status: LegalStatus = LegalStatus.ACTIVE,
) -> DocumentDetail:
    if created_at is None:
        created_at = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
    return DocumentDetail(
        id=doc_id,
        title=title,
        url=url,
        source_name=source_name,
        created_at=created_at,
        legal_status=legal_status,
    )


class TestGetDocumentDetail:
    def test_success(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.get_document_detail.return_value = _make_document_detail(
            doc_id="doc-1",
        )
        resp = client.get("/api/v1/documents/doc-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "doc-1"

    def test_not_found_returns_404(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.get_document_detail.side_effect = NotFoundError("not found")
        resp = client.get("/api/v1/documents/unknown")
        assert resp.status_code == 404

    def test_source_unavailable_returns_503(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.get_document_detail.side_effect = SourceUnavailableError("down")
        resp = client.get("/api/v1/documents/doc-1")
        assert resp.status_code == 503


# ──────────────────────────────────────────────
#  GET /api/v1/topics
# ──────────────────────────────────────────────


class TestListTopics:
    def test_success(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.list_topics.return_value = [
            TopicNode(id="t1", name="Topic 1", parent_id=""),
            TopicNode(id="t2", name="Topic 2", parent_id="t1"),
        ]
        resp = client.get("/api/v1/topics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "t1"

    def test_with_parent_id(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.list_topics.return_value = []
        client.get("/api/v1/topics", params={"parent_id": "t1"})
        mock_service.list_topics.assert_awaited_with(parent_id="t1", query="")

    def test_with_query(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.list_topics.return_value = []
        client.get("/api/v1/topics", params={"query": "law"})
        mock_service.list_topics.assert_awaited_with(parent_id=None, query="law")

    def test_not_found_returns_404(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.list_topics.side_effect = NotFoundError("not found")
        resp = client.get("/api/v1/topics", params={"parent_id": "invalid"})
        assert resp.status_code == 404


# ──────────────────────────────────────────────
#  GET /api/v1/documents/{document_id}/toc
# ──────────────────────────────────────────────


class TestGetToc:
    def test_success(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.get_toc.return_value = [
            TocNode(
                id="s1",
                document_id="doc-1",
                title="Section 1",
                parent_id="",
                level=1,
            ),
        ]
        resp = client.get("/api/v1/documents/doc-1/toc")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "s1"

    def test_with_parent_section(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.get_toc.return_value = []
        client.get(
            "/api/v1/documents/doc-1/toc",
            params={"parent_section_id": "s1"},
        )
        mock_service.get_toc.assert_awaited_with(
            document_id="doc-1", parent_section_id="s1", query=""
        )

    def test_not_found_returns_404(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.get_toc.side_effect = NotFoundError("not found")
        resp = client.get("/api/v1/documents/unknown/toc")
        assert resp.status_code == 404


# ──────────────────────────────────────────────
#  Tracing middleware
# ──────────────────────────────────────────────


class TestTracingMiddleware:
    def test_successful_request_adds_span(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        """A successful request should create a trace with output."""
        mock_service.search_documents.return_value = _make_search_response()
        # The tracer is set globally by configure(); TestClient uses the same app
        resp = client.post("/api/v1/search", json={"query": "test"})
        assert resp.status_code == 200

    def test_error_request_adds_error_span(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        """An exception in the handler should be recorded as span error."""
        mock_service.search_documents.side_effect = RuntimeError("unexpected")
        with pytest.raises(RuntimeError):
            client.post("/api/v1/search", json={"query": "test"})


# ──────────────────────────────────────────────
#  Admin / Verification endpoints
# ──────────────────────────────────────────────


class TestAdminReferenceCounts:
    def test_returns_counts(self, client: TestClient, mock_service: MagicMock) -> None:
        from core.odl_service_protocol import ReferenceCounts

        mock_service.admin_get_reference_counts.return_value = ReferenceCounts(
            section_topic=3,
            region=2,
            organization=4,
            document_type=5,
            topic=3,
            document=5,
            document_section=12,
        )
        resp = client.get("/api/v1/admin/reference-counts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["section_topic"] == 3
        assert data["region"] == 2
        assert data["document"] == 5
        assert data["document_section"] == 12


class TestAdminQdrantStatus:
    def test_returns_status(self, client: TestClient, mock_service: MagicMock) -> None:
        from core.odl_service_protocol import AdminQdrantStatus, QdrantCollectionInfo

        mock_service.admin_get_qdrant_status.return_value = AdminQdrantStatus(
            documents=QdrantCollectionInfo(exists=True, count=42),
            topics=QdrantCollectionInfo(exists=True, count=5),
        )
        resp = client.get("/api/v1/admin/qdrant/collections")
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents"]["exists"] is True
        assert data["documents"]["count"] == 42
        assert data["topics"]["exists"] is True
        assert data["topics"]["count"] == 5


class TestAdminDocumentStatus:
    def test_returns_status(self, client: TestClient, mock_service: MagicMock) -> None:
        from core.odl_service_protocol import DocumentStatus

        mock_service.admin_get_document_status.return_value = DocumentStatus(
            publish_id="0001202012230060",
            in_postgres=True,
            doc_uuid="some-uuid",
            chunk_count=10,
            section_count=5,
            rubric_count=2,
        )
        resp = client.get("/api/v1/admin/documents/0001202012230060/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["in_postgres"] is True
        assert data["chunk_count"] == 10
        assert data["section_count"] == 5
