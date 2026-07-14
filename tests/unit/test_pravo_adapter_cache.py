"""Unit tests for PravoAdapter stale cache fallback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.pravo.adapter import PravoAdapter
from adapters.pravo.adapter.constants import _STALE_CACHE_TTL
from core.errors import SourceUnavailableError
from core.models.models import (
    LegalStatus,
    OfficialDocument,
    Source,
)


@pytest.fixture
def sample_document() -> OfficialDocument:
    """A minimal OfficialDocument for cache testing."""
    return OfficialDocument(
        id="pravo-0001202012230060",
        title="Test Document",
        source=Source(id="pravo", name="Test Source", url="http://example.com"),
        url="http://example.com/doc",
        summary="Test summary",
        jurisdiction="federal",
        organization="Test Org",
        topic=["test"],
        document_number="123",
        document_type="Order",
        publish_id="0001202012230060",
        publish_date=datetime(2020, 12, 23, tzinfo=timezone.utc),
        valid_from=datetime(2020, 9, 29, tzinfo=timezone.utc),
        created_at=datetime.now(timezone.utc),
        legal_status=LegalStatus.ACTIVE,
        meta={},
    )


@pytest.fixture
def mock_tracer() -> MagicMock:
    """A mock Tracer that returns a mock _Span context manager."""
    tracer = MagicMock()
    span = MagicMock()
    span.__enter__.return_value = span
    span.__exit__.return_value = None
    tracer.trace.return_value = span
    return tracer


class TestGetStaleCached:
    """_get_stale_cached() helper method."""

    def test_returns_none_when_cache_empty(self) -> None:
        adapter = PravoAdapter(mode="stub")
        assert adapter._get_stale_cached("pravo-nonexistent") is None

    def test_returns_document_when_fresh(self, sample_document: OfficialDocument) -> None:
        adapter = PravoAdapter(mode="stub")
        doc_id = "pravo-0001202012230060"
        adapter._document_cache[doc_id] = (sample_document, datetime.now(timezone.utc))
        result = adapter._get_stale_cached(doc_id)
        assert result is sample_document

    def test_returns_none_when_expired(self, sample_document: OfficialDocument) -> None:
        adapter = PravoAdapter(mode="stub")
        doc_id = "pravo-0001202012230060"
        # Cache entry older than TTL
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STALE_CACHE_TTL + 1)
        adapter._document_cache[doc_id] = (sample_document, old_time)
        result = adapter._get_stale_cached(doc_id)
        assert result is None
        # Entry should be removed from cache
        assert doc_id not in adapter._document_cache

    def test_removes_expired_entry(self, sample_document: OfficialDocument) -> None:
        """Expired entries are evicted from the cache dict."""
        adapter = PravoAdapter(mode="stub")
        doc_id = "pravo-0001202012230060"
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STALE_CACHE_TTL + 10)
        adapter._document_cache[doc_id] = (sample_document, old_time)
        adapter._get_stale_cached(doc_id)
        assert doc_id not in adapter._document_cache

    def test_keeps_fresh_entry(self, sample_document: OfficialDocument) -> None:
        """Fresh entries remain in the cache dict after access."""
        adapter = PravoAdapter(mode="stub")
        doc_id = "pravo-0001202012230060"
        adapter._document_cache[doc_id] = (sample_document, datetime.now(timezone.utc))
        adapter._get_stale_cached(doc_id)
        assert doc_id in adapter._document_cache

    def test_entry_at_ttl_boundary_is_fresh(self, sample_document: OfficialDocument) -> None:
        """Entry at exactly TTL boundary is still considered fresh (age > TTL is expired)."""
        adapter = PravoAdapter(mode="stub")
        doc_id = "pravo-0001202012230060"
        # Use a small epsilon to ensure age < TTL even with execution delay
        epsilon = 0.001  # 1ms
        boundary_time = datetime.now(timezone.utc) - timedelta(seconds=_STALE_CACHE_TTL - epsilon)
        adapter._document_cache[doc_id] = (sample_document, boundary_time)
        result = adapter._get_stale_cached(doc_id)
        assert result is sample_document
        assert doc_id in adapter._document_cache


class TestGetStaleCacheFallback:
    """Stale cache fallback in get() when API is unavailable."""

    @pytest.mark.asyncio
    async def test_falls_back_to_stale_cache(
        self, sample_document: OfficialDocument, mock_tracer: MagicMock
    ) -> None:
        """When API raises SourceUnavailableError and stale cache exists, return it."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        doc_id = "pravo-0001202012230060"
        publish_id = "0001202012230060"

        # Pre-populate stale cache
        adapter._document_cache[doc_id] = (sample_document, datetime.now(timezone.utc))

        # Mock client to raise SourceUnavailableError
        adapter._pravo_client.get_document = AsyncMock(
            side_effect=SourceUnavailableError("API down")
        )
        adapter._parser.parse_document = MagicMock()  # Should not be called

        result = await adapter.get(doc_id)
        assert result is sample_document
        adapter._pravo_client.get_document.assert_awaited_once_with(publish_id)
        adapter._parser.parse_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_when_no_stale_cache(self, mock_tracer: MagicMock) -> None:
        """When API raises SourceUnavailableError and no stale cache, re-raise."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        doc_id = "pravo-0001202012230060"

        # Mock client to raise SourceUnavailableError
        adapter._pravo_client.get_document = AsyncMock(
            side_effect=SourceUnavailableError("API down")
        )

        with pytest.raises(SourceUnavailableError) as exc_info:
            await adapter.get(doc_id)

        error_msg = str(exc_info.value)
        assert "circuit" in error_msg.lower() or "unavailable" in error_msg.lower()
        assert doc_id in error_msg

    @pytest.mark.asyncio
    async def test_raises_when_stale_cache_expired(
        self, sample_document: OfficialDocument, mock_tracer: MagicMock
    ) -> None:
        """When stale cache exists but is expired, re-raise SourceUnavailableError."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        doc_id = "pravo-0001202012230060"

        # Pre-populate expired stale cache
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STALE_CACHE_TTL + 1)
        adapter._document_cache[doc_id] = (sample_document, old_time)

        # Mock client to raise SourceUnavailableError
        adapter._pravo_client.get_document = AsyncMock(
            side_effect=SourceUnavailableError("API down")
        )

        with pytest.raises(SourceUnavailableError):
            await adapter.get(doc_id)

        # Expired entry should be removed
        assert doc_id not in adapter._document_cache

    @pytest.mark.asyncio
    async def test_caches_after_successful_fetch(
        self, sample_document: OfficialDocument, mock_tracer: MagicMock
    ) -> None:
        """After a successful API call, the document is cached."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        doc_id = "pravo-0001202012230060"
        publish_id = "0001202012230060"

        # Mock client to return raw data
        raw_data: dict[str, object] = {"id": publish_id, "title": "Test"}
        adapter._pravo_client.get_document = AsyncMock(return_value=raw_data)
        adapter._parser.parse_document = MagicMock(return_value=sample_document)

        result = await adapter.get(doc_id)
        assert result is sample_document

        # Document should be cached
        assert doc_id in adapter._document_cache
        cached_doc, cache_time = adapter._document_cache[doc_id]
        assert cached_doc is sample_document
        assert isinstance(cache_time, datetime)

    @pytest.mark.asyncio
    async def test_stale_cache_not_used_on_success(
        self, sample_document: OfficialDocument, mock_tracer: MagicMock
    ) -> None:
        """When API succeeds, stale cache is not used."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        doc_id = "pravo-0001202012230060"
        publish_id = "0001202012230060"

        # Pre-populate stale cache with a different document
        old_doc = OfficialDocument(
            id=doc_id,
            title="Old Document",
            source=sample_document.source,
            url=sample_document.url,
            summary="Old summary",
            jurisdiction="federal",
            organization="Test Org",
            topic=["test"],
            document_number="123",
            document_type="Order",
            publish_id=publish_id,
            publish_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc),
            legal_status=LegalStatus.ACTIVE,
            meta={},
        )
        adapter._document_cache[doc_id] = (old_doc, datetime.now(timezone.utc))

        # Mock client to return raw data
        raw_data: dict[str, object] = {"id": publish_id, "title": "New"}
        adapter._pravo_client.get_document = AsyncMock(return_value=raw_data)
        adapter._parser.parse_document = MagicMock(return_value=sample_document)

        result = await adapter.get(doc_id)
        # Should return the fresh document, not the stale one
        assert result is sample_document
        assert result.title == "Test Document"

    @pytest.mark.asyncio
    async def test_circuit_state_in_error_message(self, mock_tracer: MagicMock) -> None:
        """Error message includes circuit state when no stale cache."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        doc_id = "pravo-0001202012230060"

        # Mock client to raise SourceUnavailableError
        adapter._pravo_client.get_document = AsyncMock(
            side_effect=SourceUnavailableError("API down")
        )

        with pytest.raises(SourceUnavailableError) as exc_info:
            await adapter.get(doc_id)

        error_msg = str(exc_info.value)
        # Circuit state should be mentioned (CLOSED initially)
        assert "circuit" in error_msg.lower()
