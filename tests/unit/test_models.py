"""Unit tests for canonical Pydantic models (core/models/models.py).

Tests cover:
- Field validation (bounds, defaults, types)
- Nested model construction
- Enum values
- Serialization / deserialization
- Edge cases (empty strings, None values, boundary values)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.models.models import (
    Citation,
    ConfidenceSignals,
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

# ──────────────────────────────────────────────
#  Source
# ──────────────────────────────────────────────


class TestSource:
    def test_minimal(self) -> None:
        s = Source(id="src-1", name="Test Source", url="https://example.gov")
        assert s.id == "src-1"
        assert s.name == "Test Source"
        assert s.url == "https://example.gov"
        assert s.jurisdiction is None

    def test_with_jurisdiction(self) -> None:
        s = Source(
            id="src-1",
            name="Test Source",
            url="https://example.gov",
            jurisdiction="федеральная",
        )
        assert s.jurisdiction == "федеральная"


class TestEmptyIdRejection:
    """All models with min_length=1 on their id field should reject empty strings."""

    def test_source_empty_id(self) -> None:
        with pytest.raises(ValidationError):
            Source(id="", name="Test", url="http://example.com")

    def test_official_document_empty_id(self) -> None:
        source = Source(id="s", name="S", url="http://example.com")
        with pytest.raises(ValidationError):
            OfficialDocument(id="", title="Test", source=source, url="http://example.com/doc")

    def test_search_result_empty_id(self) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=0.5,
            data_freshness=now,
            source_availability=SourceAvailability.AVAILABLE,
        )
        with pytest.raises(ValidationError):
            SearchResult(
                id="",
                title="T",
                snippet="S",
                url="http://example.com",
                source_name="Src",
                created_at=now,
                legal_status=LegalStatus.UNKNOWN,
                confidence=cs,
            )

    def test_topic_node_empty_id(self) -> None:
        with pytest.raises(ValidationError):
            TopicNode(id="", name="N", parent_id="root")

    def test_toc_node_empty_id(self) -> None:
        with pytest.raises(ValidationError):
            TocNode(id="", document_id="d", title="T", parent_id="root", level=0)


# ──────────────────────────────────────────────
#  Citation
# ──────────────────────────────────────────────


class TestCitation:
    def test_minimal(self) -> None:
        c = Citation(text="quote", source_id="doc-1", url="http://example.com")
        assert c.text == "quote"
        assert c.span_start is None
        assert c.span_end is None

    def test_with_spans(self) -> None:
        c = Citation(
            text="quote",
            source_id="doc-1",
            url="http://example.com",
            span_start=10,
            span_end=42,
        )
        assert c.span_start == 10
        assert c.span_end == 42


# ──────────────────────────────────────────────
#  ConfidenceSignals
# ──────────────────────────────────────────────


class TestConfidenceSignals:
    def test_minimal(self) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=0.85,
            data_freshness=now,
            source_availability=SourceAvailability.AVAILABLE,
        )
        assert cs.retrieval_relevance == 0.85
        assert cs.data_freshness == now
        assert cs.source_availability == SourceAvailability.AVAILABLE

    @pytest.mark.parametrize("value", [-0.01, 1.01, 1.5, -1.0])
    def test_retrieval_relevance_out_of_bounds(self, value: float) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            ConfidenceSignals(
                retrieval_relevance=value,
                data_freshness=now,
                source_availability=SourceAvailability.AVAILABLE,
            )

    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_retrieval_relevance_boundary(self, value: float) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=value,
            data_freshness=now,
            source_availability=SourceAvailability.AVAILABLE,
        )
        assert cs.retrieval_relevance == value


# ──────────────────────────────────────────────
#  OfficialDocument
# ──────────────────────────────────────────────


class TestOfficialDocument:
    def test_minimal(self) -> None:
        source = Source(id="src", name="Src", url="http://example.com")
        doc = OfficialDocument(
            id="doc-1", title="Test", source=source, url="http://example.com/doc"
        )
        assert doc.id == "doc-1"
        assert doc.title == "Test"
        assert doc.source == source
        assert doc.summary is None
        assert doc.jurisdiction is None
        assert doc.region is None
        assert doc.topic == []
        assert doc.organization is None
        assert doc.legal_status == LegalStatus.UNKNOWN
        assert doc.valid_from is None
        assert doc.valid_to is None
        # created_at should be auto-set to now (UTC)
        assert isinstance(doc.created_at, datetime)
        assert doc.created_at.tzinfo is not None

    def test_with_all_fields(self) -> None:
        now = datetime.now(timezone.utc)
        source = Source(id="src", name="Src", url="http://example.com")
        doc = OfficialDocument(
            id="doc-1",
            title="Test",
            source=source,
            url="http://example.com/doc",
            summary="A summary",
            jurisdiction="федеральная",
            region="Московская область",
            topic=["налоги", "земельное право"],
            organization="ФНС",
            organization_id="org-guid-1",
            document_type_id="doc-type-guid-1",
            created_at=now,
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
            valid_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
            legal_status=LegalStatus.ACTIVE,
        )
        assert doc.summary == "A summary"
        assert doc.jurisdiction == "федеральная"
        assert doc.region == "Московская область"
        assert doc.topic == ["налоги", "земельное право"]
        assert doc.organization == "ФНС"
        assert doc.organization_id == "org-guid-1"
        assert doc.document_type_id == "doc-type-guid-1"
        assert doc.created_at == now
        assert doc.valid_from == datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert doc.valid_to == datetime(2026, 12, 31, tzinfo=timezone.utc)
        assert doc.legal_status == LegalStatus.ACTIVE

    def test_valid_to_none_indefinite(self) -> None:
        source = Source(id="src", name="Src", url="http://example.com")
        doc = OfficialDocument(
            id="doc-1",
            title="Test",
            source=source,
            url="http://example.com/doc",
            valid_to=None,
        )
        assert doc.valid_to is None

    def test_serialize_to_dict(self) -> None:
        source = Source(id="src", name="Src", url="http://example.com")
        doc = OfficialDocument(
            id="doc-1", title="Test", source=source, url="http://example.com/doc"
        )
        d = doc.model_dump()
        assert d["id"] == "doc-1"
        assert d["title"] == "Test"
        assert d["source"]["id"] == "src"
        assert d["legal_status"] == "unknown"

    def test_serialize_to_json(self) -> None:
        source = Source(id="src", name="Src", url="http://example.com")
        doc = OfficialDocument(
            id="doc-1", title="Test", source=source, url="http://example.com/doc"
        )
        json_str = doc.model_dump_json()
        # Pydantic v2 serializes without extra spaces
        assert '"id":"doc-1"' in json_str
        assert '"legal_status":"unknown"' in json_str
        # datetime should be ISO format
        assert "created_at" in json_str

    def test_deserialize_from_dict(self) -> None:
        now = datetime.now(timezone.utc)
        data = {
            "id": "doc-1",
            "title": "Test",
            "source": {"id": "src", "name": "Src", "url": "http://example.com"},
            "url": "http://example.com/doc",
            "created_at": now.isoformat(),
            "legal_status": "active",
        }
        doc = OfficialDocument.model_validate(data)
        assert doc.id == "doc-1"
        assert doc.legal_status == LegalStatus.ACTIVE
        assert doc.source.id == "src"


# ──────────────────────────────────────────────
#  SearchContext
# ──────────────────────────────────────────────


class TestSearchContext:
    def test_defaults(self) -> None:
        ctx = SearchContext()
        assert ctx.region is None
        assert ctx.topic is None
        assert ctx.organization is None
        assert ctx.official_only is False
        assert ctx.max_age_days is None
        assert ctx.max_results == 10
        assert ctx.offset == 0

    def test_with_values(self) -> None:
        ctx = SearchContext(
            region="Москва",
            topic=["налоги", "земельное право"],
            organization=["ФНС", "Минюст"],
            official_only=True,
            max_age_days=30,
            max_results=25,
            offset=50,
        )
        assert ctx.region == "Москва"
        assert ctx.topic == ["налоги", "земельное право"]
        assert ctx.organization == ["ФНС", "Минюст"]
        assert ctx.official_only is True
        assert ctx.max_age_days == 30
        assert ctx.max_results == 25
        assert ctx.offset == 50

    @pytest.mark.parametrize("value", [0, -1, 51, 100])
    def test_max_results_out_of_bounds(self, value: int) -> None:
        with pytest.raises(ValidationError):
            SearchContext(max_results=value)

    @pytest.mark.parametrize("value", [1, 10, 50])
    def test_max_results_boundary(self, value: int) -> None:
        ctx = SearchContext(max_results=value)
        assert ctx.max_results == value

    def test_offset_default(self) -> None:
        ctx = SearchContext()
        assert ctx.offset == 0

    def test_offset_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SearchContext(offset=-1)

    def test_max_age_days_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SearchContext(max_age_days=0)

    def test_max_age_days_none_allowed(self) -> None:
        ctx = SearchContext(max_age_days=None)
        assert ctx.max_age_days is None


# ──────────────────────────────────────────────
#  SearchResult
# ──────────────────────────────────────────────


class TestSearchResult:
    def test_full_construction(self) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=0.95,
            data_freshness=now,
            source_availability=SourceAvailability.AVAILABLE,
        )
        result = SearchResult(
            id="doc-1",
            title="Test Doc",
            snippet="Some snippet",
            url="http://example.com/doc",
            source_name="Test Source",
            jurisdiction="федеральная",
            region="Московская область",
            topic=["налоги", "земельное право"],
            organization=["ФНС", "Минюст"],
            created_at=now,
            legal_status=LegalStatus.ACTIVE,
            confidence=cs,
        )
        assert result.id == "doc-1"
        assert result.jurisdiction == "федеральная"
        assert result.region == "Московская область"
        assert result.topic == ["налоги", "земельное право"]
        assert result.organization == ["ФНС", "Минюст"]
        assert result.confidence.retrieval_relevance == 0.95
        assert result.confidence.source_availability == SourceAvailability.AVAILABLE

    def test_defaults(self) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=0.5,
            data_freshness=now,
            source_availability=SourceAvailability.AVAILABLE,
        )
        result = SearchResult(
            id="doc-1",
            title="Test",
            snippet="snip",
            url="http://example.com",
            source_name="Src",
            created_at=now,
            legal_status=LegalStatus.UNKNOWN,
            confidence=cs,
        )
        assert result.jurisdiction is None
        assert result.region is None
        assert result.topic == []
        assert result.organization == []

    def test_serialize_roundtrip(self) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=0.5,
            data_freshness=now,
            source_availability=SourceAvailability.DEGRADED,
        )
        result = SearchResult(
            id="doc-1",
            title="Test",
            snippet="snip",
            url="http://example.com",
            source_name="Src",
            jurisdiction="федеральная",
            region="Московская область",
            topic=["налоги"],
            organization=["ФНС"],
            created_at=now,
            legal_status=LegalStatus.MODIFIED,
            confidence=cs,
        )
        d = result.model_dump()
        assert d["legal_status"] == "modified"
        assert d["jurisdiction"] == "федеральная"
        assert d["region"] == "Московская область"
        assert d["topic"] == ["налоги"]
        assert d["organization"] == ["ФНС"]
        assert d["confidence"]["source_availability"] == "degraded"
        assert d["confidence"]["retrieval_relevance"] == 0.5


# ──────────────────────────────────────────────
#  SearchResponse
# ──────────────────────────────────────────────


class TestSearchResponse:
    def test_minimal(self) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=0.5,
            data_freshness=now,
            source_availability=SourceAvailability.AVAILABLE,
        )
        result = SearchResult(
            id="doc-1",
            title="Test",
            snippet="snip",
            url="http://example.com",
            source_name="Src",
            created_at=now,
            legal_status=LegalStatus.ACTIVE,
            confidence=cs,
        )
        response = SearchResponse(results=[result], total_count=1, offset=0)
        assert len(response.results) == 1
        assert response.results[0].id == "doc-1"
        assert response.total_count == 1
        assert response.offset == 0

    def test_empty_results(self) -> None:
        response = SearchResponse(results=[], total_count=0, offset=0)
        assert response.results == []
        assert response.total_count == 0

    def test_pagination_metadata(self) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=0.5,
            data_freshness=now,
            source_availability=SourceAvailability.AVAILABLE,
        )
        results = [
            SearchResult(
                id=f"doc-{i}",
                title=f"Doc {i}",
                snippet="snip",
                url=f"http://example.com/doc-{i}",
                source_name="Src",
                created_at=now,
                legal_status=LegalStatus.ACTIVE,
                confidence=cs,
            )
            for i in range(3)
        ]
        response = SearchResponse(results=results, total_count=47, offset=10)
        assert len(response.results) == 3
        assert response.total_count == 47
        assert response.offset == 10
        # Агент проверяет: offset + len(results) < total_count → есть ещё страницы
        assert response.offset + len(response.results) < response.total_count

    def test_serialize_to_dict(self) -> None:
        now = datetime.now(timezone.utc)
        cs = ConfidenceSignals(
            retrieval_relevance=0.5,
            data_freshness=now,
            source_availability=SourceAvailability.AVAILABLE,
        )
        result = SearchResult(
            id="doc-1",
            title="Test",
            snippet="snip",
            url="http://example.com",
            source_name="Src",
            created_at=now,
            legal_status=LegalStatus.ACTIVE,
            confidence=cs,
        )
        response = SearchResponse(results=[result], total_count=1, offset=0)
        d = response.model_dump()
        assert d["total_count"] == 1
        assert d["offset"] == 0
        assert len(d["results"]) == 1
        assert d["results"][0]["id"] == "doc-1"


# ──────────────────────────────────────────────
#  DocumentDetail
# ──────────────────────────────────────────────


class TestDocumentDetail:
    def test_minimal(self) -> None:
        now = datetime.now(timezone.utc)
        detail = DocumentDetail(
            id="doc-1",
            title="Test Doc",
            url="http://example.com/doc",
            source_name="Test Source",
            created_at=now,
            legal_status=LegalStatus.ACTIVE,
        )
        assert detail.id == "doc-1"
        assert detail.title == "Test Doc"
        assert detail.url == "http://example.com/doc"
        assert detail.source_name == "Test Source"
        assert detail.jurisdiction is None
        assert detail.region is None
        assert detail.topic == []
        assert detail.organization == []
        assert detail.created_at == now
        assert detail.valid_from is None
        assert detail.valid_to is None
        assert detail.legal_status == LegalStatus.ACTIVE
        assert detail.citations == []
        assert detail.toc == []

    def test_with_all_fields(self) -> None:
        now = datetime.now(timezone.utc)
        citation = Citation(
            text="Цитата текста",
            source_id="doc-1",
            url="http://example.com/doc#section-1",
            section=["Раздел I", "Глава 2", "Статья 10"],
            span_start=100,
            span_end=200,
        )
        toc_node = TocNode(
            id="sec-1",
            document_id="doc-1",
            title="Раздел 1",
            parent_id="root",
            level=0,
            child_count=2,
        )
        detail = DocumentDetail(
            id="doc-1",
            title="Test Doc",
            url="http://example.com/doc",
            source_name="Test Source",
            jurisdiction="федеральная",
            region="Московская область",
            topic=["налоги", "земельное право"],
            organization=["ФНС", "Минюст"],
            created_at=now,
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
            valid_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
            legal_status=LegalStatus.ACTIVE,
            citations=[citation],
            toc=[toc_node],
        )
        assert detail.jurisdiction == "федеральная"
        assert detail.region == "Московская область"
        assert detail.topic == ["налоги", "земельное право"]
        assert detail.organization == ["ФНС", "Минюст"]
        assert detail.valid_from == datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert detail.valid_to == datetime(2026, 12, 31, tzinfo=timezone.utc)
        assert len(detail.citations) == 1
        assert detail.citations[0].text == "Цитата текста"
        assert detail.citations[0].section == ["Раздел I", "Глава 2", "Статья 10"]
        assert len(detail.toc) == 1
        assert detail.toc[0].title == "Раздел 1"
        assert detail.toc[0].level == 0

    def test_serialize_roundtrip(self) -> None:
        now = datetime.now(timezone.utc)
        detail = DocumentDetail(
            id="doc-1",
            title="Test",
            url="http://example.com",
            source_name="Src",
            created_at=now,
            legal_status=LegalStatus.UNKNOWN,
        )
        d = detail.model_dump()
        assert d["id"] == "doc-1"
        assert d["title"] == "Test"
        assert d["legal_status"] == "unknown"
        assert d["citations"] == []
        assert d["toc"] == []

    def test_empty_id_rejected(self) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            DocumentDetail(
                id="",
                title="Test",
                url="http://example.com",
                source_name="Src",
                created_at=now,
                legal_status=LegalStatus.UNKNOWN,
            )


# ──────────────────────────────────────────────
#  TopicNode
# ──────────────────────────────────────────────


class TestTopicNode:
    def test_minimal(self) -> None:
        node = TopicNode(id="topic-1", name="Налоги", parent_id="root")
        assert node.id == "topic-1"
        assert node.name == "Налоги"
        assert node.parent_id == "root"
        assert node.description is None
        assert node.child_count == 0
        assert node.document_count == 0

    def test_with_all_fields(self) -> None:
        node = TopicNode(
            id="topic-1",
            name="Налоги",
            parent_id="root",
            description="Всё о налогах",
            child_count=5,
            document_count=100,
        )
        assert node.description == "Всё о налогах"
        assert node.child_count == 5
        assert node.document_count == 100


# ──────────────────────────────────────────────
#  TocNode
# ──────────────────────────────────────────────


class TestTocNode:
    def test_minimal(self) -> None:
        node = TocNode(
            id="sec-1",
            document_id="doc-1",
            title="Раздел 1",
            parent_id="root",
            level=0,
        )
        assert node.id == "sec-1"
        assert node.level == 0
        assert node.child_count == 0

    def test_negative_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TocNode(
                id="sec-1",
                document_id="doc-1",
                title="Bad",
                parent_id="root",
                level=-1,
            )

    def test_level_boundary(self) -> None:
        node = TocNode(
            id="sec-1",
            document_id="doc-1",
            title="Root",
            parent_id="root",
            level=0,
        )
        assert node.level == 0


# ──────────────────────────────────────────────
#  LegalStatus & SourceAvailability enums
# ──────────────────────────────────────────────


class TestLegalStatus:
    def test_all_values(self) -> None:
        assert LegalStatus.ACTIVE.value == "active"
        assert LegalStatus.REVOKED.value == "revoked"
        assert LegalStatus.MODIFIED.value == "modified"
        assert LegalStatus.UNKNOWN.value == "unknown"

    def test_from_string(self) -> None:
        assert LegalStatus("active") == LegalStatus.ACTIVE
        assert LegalStatus("revoked") == LegalStatus.REVOKED

    def test_invalid_value(self) -> None:
        with pytest.raises(ValueError):
            LegalStatus("invalid_status")


class TestSourceAvailability:
    def test_all_values(self) -> None:
        assert SourceAvailability.AVAILABLE.value == "available"
        assert SourceAvailability.DEGRADED.value == "degraded"
        assert SourceAvailability.UNAVAILABLE.value == "unavailable"

    def test_from_string(self) -> None:
        assert SourceAvailability("available") == SourceAvailability.AVAILABLE
        assert SourceAvailability("unavailable") == SourceAvailability.UNAVAILABLE
