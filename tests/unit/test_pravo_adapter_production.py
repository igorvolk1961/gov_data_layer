"""Unit tests for PravoAdapter production mode scenarios.

Tests the production-mode methods added in Part C of the resilience plan:
- _ensure_caches_populated()
- _get_ocr_provider()
- ingest() in production mode
- get_content() in production mode
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.pravo.adapter import PravoAdapter
from core.errors import SourceUnavailableError


@pytest.fixture
def mock_config() -> MagicMock:
    """A mock AppConfig with ocr.provider set to a non-existent value."""
    config = MagicMock()
    config.ocr.provider = "__nonexistent__"
    return config


@pytest.fixture
def mock_tracer() -> MagicMock:
    """A mock Tracer that returns a mock _Span context manager."""
    tracer = MagicMock()
    span = MagicMock()
    span.__enter__.return_value = span
    span.__exit__.return_value = None
    tracer.trace.return_value = span
    return tracer


# ──────────────────────────────────────────────
#  _ensure_caches_populated()
# ──────────────────────────────────────────────


class TestEnsureCachesPopulated:
    """_ensure_caches_populated() helper method."""

    @pytest.mark.asyncio
    async def test_populates_caches_on_first_call(self, mock_tracer: MagicMock) -> None:
        """On first call, fetches blocks, categories, authorities, doc types."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        assert adapter._cache_populated_at is None

        # Mock client responses
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

        # Mock parser methods
        adapter._parser.update_authority_cache = MagicMock()
        adapter._parser.update_doc_type_cache = MagicMock()

        await adapter._ensure_caches_populated()

        assert adapter._cache_populated_at is not None
        adapter._pravo_client.get_public_blocks.assert_awaited_once()
        adapter._pravo_client.get_categories.assert_awaited_once_with(block="block1")
        adapter._pravo_client.get_signatory_authorities.assert_awaited_once_with(
            block="block1", category="cat1"
        )
        adapter._pravo_client.get_document_types.assert_awaited_once_with(
            block="block1", category="cat1", authority_id="auth1"
        )
        adapter._parser.update_authority_cache.assert_called_once_with(
            [{"id": "auth1", "name": "Authority 1"}]
        )
        adapter._parser.update_doc_type_cache.assert_called_once_with(
            [{"id": "type1", "name": "Type 1"}]
        )

    @pytest.mark.asyncio
    async def test_skips_when_still_fresh(self, mock_tracer: MagicMock) -> None:
        """If caches were populated recently, skip the API calls."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        adapter._cache_populated_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )

        adapter._pravo_client.get_public_blocks = AsyncMock()

        await adapter._ensure_caches_populated()

        # Should not call API since caches are fresh
        adapter._pravo_client.get_public_blocks.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_api_unavailable(self, mock_tracer: MagicMock) -> None:
        """When API is unavailable, log warning and don't update timestamp."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        assert adapter._cache_populated_at is None

        adapter._pravo_client.get_public_blocks = AsyncMock(
            side_effect=SourceUnavailableError("API down")
        )

        await adapter._ensure_caches_populated()

        # Timestamp should NOT be updated — will retry on next call
        assert adapter._cache_populated_at is None

    @pytest.mark.asyncio
    async def test_handles_empty_blocks(self, mock_tracer: MagicMock) -> None:
        """When API returns empty blocks list, skip further fetches."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)

        adapter._pravo_client.get_public_blocks = AsyncMock(return_value=[])

        await adapter._ensure_caches_populated()

        # Should not call further APIs
        adapter._pravo_client.get_categories = AsyncMock()
        adapter._pravo_client.get_categories.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_handles_empty_categories(self, mock_tracer: MagicMock) -> None:
        """When API returns empty categories list, skip authority fetch."""
        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)

        adapter._pravo_client.get_public_blocks = AsyncMock(
            return_value=[{"id": "block1", "name": "Block 1"}]
        )
        adapter._pravo_client.get_categories = AsyncMock(return_value=[])

        await adapter._ensure_caches_populated()

        # Should not call signatory authorities
        adapter._pravo_client.get_signatory_authorities = AsyncMock()
        adapter._pravo_client.get_signatory_authorities.assert_not_called()  # type: ignore[attr-defined]


# ──────────────────────────────────────────────
#  _get_ocr_provider()
# ──────────────────────────────────────────────


class TestGetOcrProvider:
    """_get_ocr_provider() helper method."""

    def test_returns_injected_provider(self, mock_tracer: MagicMock) -> None:
        """When ocr_provider is injected via constructor, return it directly."""
        mock_ocr = MagicMock()
        adapter = PravoAdapter(mode="stub", ocr_provider=mock_ocr, tracer=mock_tracer)
        result = adapter._get_ocr_provider()
        assert result is mock_ocr

    @patch("core.api.app_config.get_config")
    def test_returns_none_when_no_config(
        self, mock_get_config: MagicMock, mock_tracer: MagicMock
    ) -> None:
        """When no OCR provider is configured, return None."""
        mock_config = MagicMock()
        mock_config.ocr.provider = "__nonexistent__"
        mock_get_config.return_value = mock_config

        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        result = adapter._get_ocr_provider()
        assert result is None

    @patch("core.api.app_config.get_config")
    def test_creates_stub_from_config(
        self, mock_get_config: MagicMock, mock_tracer: MagicMock
    ) -> None:
        """When config has ocr.provider='stub', create StubOCR."""
        mock_config = MagicMock()
        mock_config.ocr.provider = "stub"
        mock_get_config.return_value = mock_config

        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        result = adapter._get_ocr_provider()

        assert result is not None
        # Should be a StubOCR instance
        assert result.__class__.__name__ == "StubOCR"

    @patch("core.api.app_config.get_config")
    def test_creates_tesseract_from_config(
        self, mock_get_config: MagicMock, mock_tracer: MagicMock
    ) -> None:
        """When config has ocr.provider='tesseract', create TesseractOCR."""
        mock_config = MagicMock()
        mock_config.ocr.provider = "tesseract"
        mock_config.ocr.tesseract_lang = "rus"
        mock_config.ocr.tesseract_timeout = 120
        mock_get_config.return_value = mock_config

        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        result = adapter._get_ocr_provider()

        assert result is not None
        assert result.__class__.__name__ == "TesseractOCR"

    @patch("core.api.app_config.get_config")
    def test_creates_yandex_vision_from_config(
        self, mock_get_config: MagicMock, mock_tracer: MagicMock
    ) -> None:
        """When config has ocr.provider='yandex_vision', create YandexVisionOCR."""
        mock_config = MagicMock()
        mock_config.ocr.provider = "yandex_vision"
        mock_config.ocr.ya_folder_id = "test-folder"
        mock_config.ocr.yandex_vision_timeout = 60
        mock_get_config.return_value = mock_config

        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        result = adapter._get_ocr_provider()

        assert result is not None
        assert result.__class__.__name__ == "YandexVisionOCR"

    @patch("core.api.app_config.get_config")
    def test_unknown_provider_returns_none(
        self, mock_get_config: MagicMock, mock_tracer: MagicMock
    ) -> None:
        """When config has unknown ocr.provider, return None."""
        mock_config = MagicMock()
        mock_config.ocr.provider = "unknown_provider"
        mock_get_config.return_value = mock_config

        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        result = adapter._get_ocr_provider()
        assert result is None

    @patch("core.api.app_config.get_config")
    def test_caches_created_provider(
        self, mock_get_config: MagicMock, mock_tracer: MagicMock
    ) -> None:
        """The OCR provider is cached after first creation."""
        mock_config = MagicMock()
        mock_config.ocr.provider = "stub"
        mock_get_config.return_value = mock_config

        adapter = PravoAdapter(mode="stub", tracer=mock_tracer)
        result1 = adapter._get_ocr_provider()
        result2 = adapter._get_ocr_provider()

        # Should return the same instance (cached)
        assert result1 is result2
        # get_config should only be called once
        mock_get_config.assert_called_once()


# ──────────────────────────────────────────────
#  ingest() in production mode
# ──────────────────────────────────────────────


class TestIngestProduction:
    """ingest() in production mode."""

    @pytest.mark.asyncio
    async def test_ingest_success(self, mock_tracer: MagicMock) -> None:
        """Successful ingest fetches documents, parses them, and caches."""
        adapter = PravoAdapter(mode="production", tracer=mock_tracer)

        # Mock _ensure_caches_populated to do nothing
        adapter._ensure_caches_populated = AsyncMock()

        # Mock search_documents to return items
        raw_items = [
            {"id": "doc1", "title": "Document 1"},
            {"id": "doc2", "title": "Document 2"},
        ]
        adapter._pravo_client.search_documents = AsyncMock(return_value={"items": raw_items})

        # Mock parser to return documents
        mock_doc1 = MagicMock()
        mock_doc1.id = "pravo-doc1"
        mock_doc2 = MagicMock()
        mock_doc2.id = "pravo-doc2"
        adapter._parser.parse_search_result = MagicMock(side_effect=[mock_doc1, mock_doc2])

        # Mock get_content to avoid needing OCR/PDF download during ingest
        adapter.get_content = AsyncMock(return_value="test text")

        count = await adapter.ingest()

        assert count == 2
        adapter._ensure_caches_populated.assert_awaited()
        adapter._parser.parse_search_result.assert_any_call(raw_items[0])
        adapter._parser.parse_search_result.assert_any_call(raw_items[1])

        # Documents should be cached
        assert "pravo-doc1" in adapter._document_cache
        assert "pravo-doc2" in adapter._document_cache

    @pytest.mark.asyncio
    async def test_ingest_handles_parse_errors(self, mock_tracer: MagicMock) -> None:
        """When some items fail to parse, skip them and continue."""
        adapter = PravoAdapter(mode="production", tracer=mock_tracer)

        adapter._ensure_caches_populated = AsyncMock()
        raw_items = [
            {"id": "doc1", "title": "Document 1"},
            {"id": "doc2", "title": "Document 2"},
            {"id": "doc3", "title": "Document 3"},
        ]
        adapter._pravo_client.search_documents = AsyncMock(return_value={"items": raw_items})

        # Second item fails to parse
        mock_doc1 = MagicMock()
        mock_doc1.id = "pravo-doc1"
        mock_doc3 = MagicMock()
        mock_doc3.id = "pravo-doc3"
        adapter._parser.parse_search_result = MagicMock(
            side_effect=[mock_doc1, ValueError("Bad data"), mock_doc3]
        )

        # Mock get_content to avoid needing OCR/PDF download during ingest
        adapter.get_content = AsyncMock(return_value="test text")

        count = await adapter.ingest()

        # Should have skipped the bad item
        assert count == 2
        assert "pravo-doc1" in adapter._document_cache
        assert "pravo-doc3" in adapter._document_cache

    @pytest.mark.asyncio
    async def test_ingest_returns_zero_on_api_unavailable(self, mock_tracer: MagicMock) -> None:
        """When API is unavailable, ingest returns 0 gracefully."""
        adapter = PravoAdapter(mode="production", tracer=mock_tracer)

        adapter._ensure_caches_populated = AsyncMock()
        adapter._pravo_client.search_documents = AsyncMock(
            side_effect=SourceUnavailableError("API down")
        )

        count = await adapter.ingest()

        assert count == 0

    @pytest.mark.asyncio
    async def test_ingest_handles_empty_response(self, mock_tracer: MagicMock) -> None:
        """When API returns no items, ingest returns 0."""
        adapter = PravoAdapter(mode="production", tracer=mock_tracer)

        adapter._ensure_caches_populated = AsyncMock()
        adapter._pravo_client.search_documents = AsyncMock(return_value={"items": []})

        count = await adapter.ingest()

        assert count == 0


# ──────────────────────────────────────────────
#  get_content() in production mode
# ──────────────────────────────────────────────


class TestGetContentProduction:
    """get_content() in production mode."""

    @pytest.mark.asyncio
    async def test_get_content_success(self, mock_tracer: MagicMock) -> None:
        """Successful get_content downloads PDF and extracts text via OCR."""
        mock_ocr = MagicMock()
        mock_ocr.extract_text = AsyncMock(return_value="Extracted text content")
        adapter = PravoAdapter(mode="production", ocr_provider=mock_ocr, tracer=mock_tracer)

        publish_id = "0001202012230060"
        document_id = f"pravo-{publish_id}"

        # Mock PDF download
        pdf_bytes = b"%PDF-1.4 fake pdf content"
        adapter._pravo_client.download_pdf = AsyncMock(return_value=pdf_bytes)

        result = await adapter.get_content(document_id)

        assert result == "Extracted text content"
        adapter._pravo_client.download_pdf.assert_awaited_once_with(publish_id)
        mock_ocr.extract_text.assert_awaited_once_with(pdf_bytes, document_id)

    @pytest.mark.asyncio
    async def test_get_content_raises_when_no_ocr(self, mock_tracer: MagicMock) -> None:
        """When no OCR provider is configured, raise SourceUnavailableError."""
        adapter = PravoAdapter(mode="production", tracer=mock_tracer)
        # Mock _get_ocr_provider to return None
        adapter._get_ocr_provider = MagicMock(return_value=None)  # type: ignore[method-assign]

        document_id = "pravo-0001202012230060"

        with pytest.raises(SourceUnavailableError) as exc_info:
            await adapter.get_content(document_id)

        error_msg = str(exc_info.value)
        assert "OCR provider" in error_msg
        assert document_id in error_msg

    @pytest.mark.asyncio
    async def test_get_content_handles_pdf_download_failure(self, mock_tracer: MagicMock) -> None:
        """When PDF download fails, raise SourceUnavailableError."""
        mock_ocr = MagicMock()
        adapter = PravoAdapter(mode="production", ocr_provider=mock_ocr, tracer=mock_tracer)

        document_id = "pravo-0001202012230060"

        adapter._pravo_client.download_pdf = AsyncMock(
            side_effect=SourceUnavailableError("PDF download failed")
        )

        with pytest.raises(SourceUnavailableError) as exc_info:
            await adapter.get_content(document_id)

        error_msg = str(exc_info.value)
        assert document_id in error_msg

    @pytest.mark.asyncio
    async def test_get_content_handles_ocr_failure(self, mock_tracer: MagicMock) -> None:
        """When OCR extraction fails, raise SourceUnavailableError."""
        mock_ocr = MagicMock()
        mock_ocr.extract_text = AsyncMock(side_effect=RuntimeError("OCR engine crashed"))
        adapter = PravoAdapter(mode="production", ocr_provider=mock_ocr, tracer=mock_tracer)

        document_id = "pravo-0001202012230060"

        adapter._pravo_client.download_pdf = AsyncMock(return_value=b"%PDF fake")

        with pytest.raises(SourceUnavailableError) as exc_info:
            await adapter.get_content(document_id)

        error_msg = str(exc_info.value)
        assert document_id in error_msg
        assert "OCR" in error_msg or "Unexpected" in error_msg
