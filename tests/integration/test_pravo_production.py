"""Integration tests for PravoAdapter production mode.

Tests the full adapter flow with mocked API responses but real adapter
orchestration: cache population, ingest, get_content with OCR.

These tests verify that the adapter correctly wires together:
- PravoClient (mocked at HTTP level)
- PravoParser
- OCR provider (mocked)
- Circuit breaker
- Stale cache fallback
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.pravo.adapter import PravoAdapter
from core.errors import SourceUnavailableError


@pytest.fixture
def mock_tracer() -> MagicMock:
    """A mock Tracer that returns a mock _Span context manager."""
    tracer = MagicMock()
    span = MagicMock()
    span.__enter__.return_value = span
    span.__exit__.return_value = None
    tracer.trace.return_value = span
    return tracer


@pytest.fixture
def mock_ocr() -> MagicMock:
    """A mock OCR provider."""
    ocr = MagicMock()
    ocr.extract_text = AsyncMock(return_value="Extracted text from PDF")
    return ocr


@pytest.mark.asyncio
async def test_full_ingest_and_get_content_flow(
    mock_tracer: MagicMock, mock_ocr: MagicMock
) -> None:
    """Full production flow: ingest documents, then get content for one."""
    adapter = PravoAdapter(mode="production", ocr_provider=mock_ocr, tracer=mock_tracer)

    # Mock all API calls needed for cache population
    adapter._pravo_client.get_public_blocks = AsyncMock(
        return_value=[{"id": "block1", "name": "Block 1"}]
    )
    adapter._pravo_client.get_categories = AsyncMock(
        return_value=[{"id": "cat1", "name": "Category 1"}]
    )
    adapter._pravo_client.get_signatory_authorities = AsyncMock(
        return_value=[{"id": "auth1", "name": "Authority 1"}]
    )
    adapter._pravo_client.get_document_types = AsyncMock(
        return_value=[{"id": "type1", "name": "Type 1"}]
    )

    # Mock search_documents for ingest
    raw_items = [
        {
            "id": "doc1",
            "title": "Test Document 1",
            "eoNumber": "0001202012230060",
        },
        {
            "id": "doc2",
            "title": "Test Document 2",
            "eoNumber": "0001202012230061",
        },
    ]
    adapter._pravo_client.search_documents = AsyncMock(return_value={"items": raw_items})

    # Mock PDF download for get_content
    adapter._pravo_client.download_pdf = AsyncMock(return_value=b"%PDF-1.4 fake pdf content")

    # Step 1: Ingest
    count = await adapter.ingest()
    assert count == 2

    # Step 2: Get content for first document
    doc_id = "pravo-0001202012230060"
    content = await adapter.get_content(doc_id)
    assert content == "Extracted text from PDF"

    # Verify the flow: download_pdf was called with the publish_id
    adapter._pravo_client.download_pdf.assert_awaited_once_with("0001202012230060")
    mock_ocr.extract_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_with_api_unavailable_then_recovers(
    mock_tracer: MagicMock,
    mock_ocr: MagicMock,
) -> None:
    """When API is down during ingest, returns 0; after recovery, works."""
    adapter = PravoAdapter(mode="production", ocr_provider=mock_ocr, tracer=mock_tracer)

    # Mock cache population to succeed
    adapter._pravo_client.get_public_blocks = AsyncMock(
        return_value=[{"id": "block1", "name": "Block 1"}]
    )
    adapter._pravo_client.get_categories = AsyncMock(
        return_value=[{"id": "cat1", "name": "Category 1"}]
    )
    adapter._pravo_client.get_signatory_authorities = AsyncMock(
        return_value=[{"id": "auth1", "name": "Authority 1"}]
    )
    adapter._pravo_client.get_document_types = AsyncMock(
        return_value=[{"id": "type1", "name": "Type 1"}]
    )

    # First call: API unavailable
    adapter._pravo_client.search_documents = AsyncMock(
        side_effect=SourceUnavailableError("API temporarily down")
    )

    count = await adapter.ingest()
    assert count == 0

    # Second call: API recovers
    adapter._pravo_client.search_documents = AsyncMock(
        return_value={
            "items": [{"id": "doc1", "title": "Recovered Doc", "eoNumber": "0001202012230062"}]
        }
    )

    count = await adapter.ingest()
    assert count == 1


@pytest.mark.asyncio
async def test_get_content_with_circuit_breaker_open(
    mock_tracer: MagicMock,
    mock_ocr: MagicMock,
) -> None:
    """When circuit breaker is open, get_content fast-fails."""
    adapter = PravoAdapter(mode="production", ocr_provider=mock_ocr, tracer=mock_tracer)

    # Force circuit breaker to open state
    cb = adapter._pravo_client.circuit_breaker
    for _ in range(cb._failure_threshold):
        cb.record_failure()

    assert cb.is_open

    document_id = "pravo-0001202012230060"
    with pytest.raises(SourceUnavailableError) as exc_info:
        await adapter.get_content(document_id)

    error_msg = str(exc_info.value)
    assert "circuit" in error_msg.lower() or "unavailable" in error_msg.lower()


@pytest.mark.asyncio
async def test_stale_cache_fallback_on_api_failure(
    mock_tracer: MagicMock,
    mock_ocr: MagicMock,
) -> None:
    """When API fails after a successful get, fall back to stale cache."""
    adapter = PravoAdapter(mode="production", ocr_provider=mock_ocr, tracer=mock_tracer)

    # Mock a successful document fetch
    adapter._pravo_client.get_document = AsyncMock(
        return_value={
            "id": "doc1-guid-12345",
            "eoNumber": "0001202012230060",
            "title": "Cached Document",
        }
    )

    document_id = "pravo-doc1-guid-12345"

    # First call: succeeds and caches
    doc = await adapter.get(document_id)
    assert doc is not None

    # Second call: API fails, should fall back to stale cache
    adapter._pravo_client.get_document = AsyncMock(side_effect=SourceUnavailableError("API down"))

    doc = await adapter.get(document_id)
    assert doc is not None
    assert doc.title == "Cached Document"
