"""Unit tests for OCR providers (adapters/ocr/).

Tests cover:
- StubOCR: predefined texts, unknown document_id, empty pdf_bytes
- TesseractOCR: init, quality checks, import errors
- YandexVisionOCR: IAM token, success path, auth retry, network retry, parse
- OCRProvider protocol compliance for all providers
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.ocr import OCRProvider, StubOCR, TesseractOCR, YandexVisionOCR
from core.errors import InvalidInputError, OCRQualityError, OCRUnavailableError

# ======================================================================
#  StubOCR
# ======================================================================


class TestStubOCR:
    """Tests for StubOCR — заглушка OCR для тестов."""

    @pytest.fixture
    def ocr(self) -> StubOCR:
        return StubOCR()

    @pytest.mark.asyncio
    async def test_extract_text_known_document(self, ocr: StubOCR) -> None:
        """Known document_id returns predefined text."""
        pdf_bytes = b"fake pdf content"
        doc_id = "0001202012230060"

        text = await ocr.extract_text(pdf_bytes, doc_id)

        assert "Министерства труда" in text
        assert "668н" in text
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_extract_text_unknown_document(self, ocr: StubOCR) -> None:
        """Unknown document_id returns template text with the id."""
        pdf_bytes = b"fake pdf content"
        doc_id = "unknown_doc_123"

        text = await ocr.extract_text(pdf_bytes, doc_id)

        assert doc_id in text
        assert "Stub OCR text" in text

    @pytest.mark.asyncio
    async def test_extract_text_empty_bytes_raises_error(self, ocr: StubOCR) -> None:
        """Empty pdf_bytes raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="pdf_bytes can't be empty"):
            await ocr.extract_text(b"", "doc_001")

    @pytest.mark.asyncio
    async def test_extract_text_multiple_known_docs(self, ocr: StubOCR) -> None:
        """All predefined documents return distinct texts."""
        doc_ids = [
            "0001202012230060",
            "0001202206200030",
            "0001202212190143",
        ]
        texts: list[str] = []
        for doc_id in doc_ids:
            text = await ocr.extract_text(b"pdf", doc_id)
            texts.append(text)

        # All texts should be different
        assert len(set(texts)) == 3
        # Each should contain relevant keywords
        assert "668н" in texts[0]
        assert "154н" in texts[1]
        assert "2330" in texts[2]

    def test_is_ocr_provider(self, ocr: StubOCR) -> None:
        """StubOCR satisfies the OCRProvider protocol."""
        assert isinstance(ocr, OCRProvider)


# ======================================================================
#  TesseractOCR
# ======================================================================


class TestTesseractOCR:
    """Tests for TesseractOCR — локальный OCR через Tesseract.

    All tests mock external dependencies (pytesseract, pdf2image) to avoid
    requiring Tesseract installation.
    """

    @pytest.fixture
    def ocr(self) -> TesseractOCR:
        return TesseractOCR()

    # ── Init ──────────────────────────────────────────────────────

    def test_default_init(self) -> None:
        """Default constructor uses expected defaults."""
        ocr = TesseractOCR()
        assert ocr._lang == "rus"
        assert ocr._timeout == 30.0

    def test_custom_init(self) -> None:
        """Custom parameters are stored correctly."""
        ocr = TesseractOCR(lang="eng", timeout=60.0)
        assert ocr._lang == "eng"
        assert ocr._timeout == 60.0

    # ── extract_text success ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_text_success(self, ocr: TesseractOCR) -> None:
        """Happy path: PDF converted, text extracted, concatenated."""
        mock_image_1 = MagicMock()
        mock_image_2 = MagicMock()

        with (
            patch("pdf2image.convert_from_bytes") as mock_convert,
            patch("pytesseract.image_to_string") as mock_tess,
        ):
            mock_convert.return_value = [mock_image_1, mock_image_2]
            mock_tess.side_effect = ["Текст первой страницы", "Текст второй страницы"]

            result = await ocr.extract_text(b"fake pdf", "doc_001")

        assert "Текст первой страницы" in result
        assert "Текст второй страницы" in result
        assert mock_convert.call_count == 1
        assert mock_tess.call_count == 2

    @pytest.mark.asyncio
    async def test_extract_text_skips_empty_pages(self, ocr: TesseractOCR) -> None:
        """Pages with only whitespace are skipped in concatenation."""
        mock_image = MagicMock()

        with (
            patch("pdf2image.convert_from_bytes") as mock_convert,
            patch("pytesseract.image_to_string") as mock_tess,
        ):
            mock_convert.return_value = [mock_image, mock_image, mock_image]
            mock_tess.side_effect = ["   ", "Реальный текст с содержанием", "Ещё немного текста"]

            result = await ocr.extract_text(b"pdf", "doc_002")

        assert "Реальный текст с содержанием" in result
        assert "   " not in result

    # ── extract_text errors ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_text_import_error(self) -> None:
        """Missing pytesseract/pdf2image raises OCRUnavailableError."""
        ocr = TesseractOCR()
        with (
            patch.dict("sys.modules", {"pytesseract": None, "pdf2image": None}),
            pytest.raises(OCRUnavailableError, match="Missing OCR dependency"),
        ):
            await ocr.extract_text(b"pdf", "doc_003")

    @pytest.mark.asyncio
    async def test_extract_text_convert_failure(self, ocr: TesseractOCR) -> None:
        """PDF conversion failure raises OCRUnavailableError."""
        with (
            patch(
                "pdf2image.convert_from_bytes",
                side_effect=RuntimeError("Corrupt PDF"),
            ),
            pytest.raises(OCRUnavailableError, match="Failed to convert PDF"),
        ):
            await ocr.extract_text(b"corrupt pdf", "doc_004")

    @pytest.mark.asyncio
    async def test_extract_text_no_pages(self, ocr: TesseractOCR) -> None:
        """Empty PDF (no pages after conversion) raises OCRQualityError."""
        with (
            patch("pdf2image.convert_from_bytes") as mock_convert,
        ):
            mock_convert.return_value = []

            with pytest.raises(OCRQualityError, match="no pages"):
                await ocr.extract_text(b"empty pdf", "doc_005")

    @pytest.mark.asyncio
    async def test_extract_text_quality_too_low(self, ocr: TesseractOCR) -> None:
        """Very short extracted text raises OCRQualityError."""
        mock_image = MagicMock()

        with (
            patch("pdf2image.convert_from_bytes") as mock_convert,
            patch("pytesseract.image_to_string") as mock_tess,
        ):
            mock_convert.return_value = [mock_image]
            mock_tess.return_value = "AB"  # shorter than _MIN_TEXT_LENGTH (20)

            with pytest.raises(OCRQualityError, match="OCR quality too low"):
                await ocr.extract_text(b"pdf", "doc_006")

    @pytest.mark.asyncio
    async def test_extract_text_tesseract_runtime_error(self, ocr: TesseractOCR) -> None:
        """Tesseract RuntimeError on a page raises OCRUnavailableError."""
        mock_image = MagicMock()

        with (
            patch("pdf2image.convert_from_bytes") as mock_convert,
            patch("pytesseract.image_to_string") as mock_tess,
        ):
            mock_convert.return_value = [mock_image]
            mock_tess.side_effect = RuntimeError("Tesseract not found")

            with pytest.raises(OCRUnavailableError, match="Tesseract OCR failed"):
                await ocr.extract_text(b"pdf", "doc_007")

    def test_is_ocr_provider(self, ocr: TesseractOCR) -> None:
        """TesseractOCR satisfies the OCRProvider protocol."""
        assert isinstance(ocr, OCRProvider)


# ======================================================================
#  YandexVisionOCR
# ======================================================================


class TestYandexVisionOCR:
    """Tests for YandexVisionOCR — OCR через Yandex Cloud OCR API v1.

    All tests mock httpx and fitz to avoid real network calls.
    """

    @pytest.fixture
    def ocr(self, ya_key_secret: str, ya_folder_id: str) -> YandexVisionOCR:
        return YandexVisionOCR(
            ya_key_secret=ya_key_secret,
            ya_folder_id=ya_folder_id,
        )

    @pytest.fixture
    def mock_single_page_response(self) -> dict[str, Any]:
        """Simulate a successful Yandex OCR API response for one page."""
        return {
            "result": {
                "textAnnotation": {
                    "fullText": "Текст первой страницы",
                },
            },
        }

    @pytest.fixture
    def mock_multi_page_responses(self) -> list[dict[str, Any]]:
        """Simulate successful responses for two pages."""
        return [
            {
                "result": {
                    "textAnnotation": {
                        "fullText": "Текст первой страницы",
                    },
                },
            },
            {
                "result": {
                    "textAnnotation": {
                        "fullText": "Текст второй страницы",
                    },
                },
            },
        ]

    # ── Init ──────────────────────────────────────────────────────

    def test_default_init(self, ya_key_secret: str, ya_folder_id: str) -> None:
        """Constructor stores parameters correctly."""
        ocr = YandexVisionOCR(
            ya_key_secret=ya_key_secret,
            ya_folder_id=ya_folder_id,
        )
        assert ocr._key_secret == ya_key_secret
        assert ocr._folder_id == ya_folder_id
        assert ocr._timeout == 120.0
        assert ocr._iam_token is None
        assert ocr._is_api_key is False

    def test_custom_timeout(self, ya_key_secret: str, ya_folder_id: str) -> None:
        """Custom timeout is stored."""
        ocr = YandexVisionOCR(
            ya_key_secret=ya_key_secret,
            ya_folder_id=ya_folder_id,
            timeout=60.0,
        )
        assert ocr._timeout == 60.0

    # ── _get_authorization_header (service account) ───────────────

    @pytest.mark.asyncio
    async def test_get_auth_header_service_account_success(self, ocr: YandexVisionOCR) -> None:
        """Successful IAM token retrieval for service account."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"iamToken": "test-token-123"}
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)

            header = await ocr._get_authorization_header()

        assert header == "Bearer test-token-123"
        assert ocr._iam_token == "test-token-123"

    @pytest.mark.asyncio
    async def test_get_auth_header_service_account_cached(self, ocr: YandexVisionOCR) -> None:
        """Cached IAM token is reused without network call."""
        ocr._iam_token = "cached-token"

        with patch("httpx.AsyncClient") as mock_client:
            header = await ocr._get_authorization_header()

        assert header == "Bearer cached-token"
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_auth_header_service_account_http_error(self, ocr: YandexVisionOCR) -> None:
        """HTTP error raises OCRUnavailableError."""
        from httpx import HTTPStatusError, Request

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = HTTPStatusError(
            "Unauthorized",
            request=MagicMock(spec=Request),
            response=mock_response,
        )

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            pytest.raises(OCRUnavailableError, match="Failed to get IAM token"),
        ):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)
            await ocr._get_authorization_header()

    @pytest.mark.asyncio
    async def test_get_auth_header_service_account_network_error(
        self, ocr: YandexVisionOCR
    ) -> None:
        """Network error raises OCRUnavailableError."""
        from httpx import RequestError

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            pytest.raises(OCRUnavailableError, match="Failed to get IAM token"),
        ):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(side_effect=RequestError("Connection timed out"))
            await ocr._get_authorization_header()

    @pytest.mark.asyncio
    async def test_get_auth_header_service_account_parse_error(self, ocr: YandexVisionOCR) -> None:
        """Malformed response raises OCRUnavailableError."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"noToken": "here"}
        mock_response.raise_for_status.return_value = None

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            pytest.raises(OCRUnavailableError, match="Failed to parse IAM token"),
        ):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)
            await ocr._get_authorization_header()

    # ── _get_authorization_header (API key) ───────────────────────

    @pytest.mark.asyncio
    async def test_get_auth_header_api_key(self, ya_api_key: str, ya_folder_id: str) -> None:
        """API key returns Api-Key header directly without network call."""
        ocr = YandexVisionOCR(
            ya_key_secret=ya_api_key,
            ya_folder_id=ya_folder_id,
        )
        assert ocr._is_api_key is True

        with patch("httpx.AsyncClient") as mock_client:
            header = await ocr._get_authorization_header()

        assert header == f"Api-Key {ya_api_key}"
        mock_client.assert_not_called()

    # ── _split_pdf_into_pages ─────────────────────────────────────

    def test_split_pdf_single_page(self, ocr: YandexVisionOCR) -> None:
        """Single-page PDF returns the original bytes unchanged."""
        pdf_bytes = b"single page pdf content"
        with patch("fitz.open") as mock_open:
            mock_doc = MagicMock(spec=["page_count", "close"])
            mock_doc.page_count = 1
            mock_open.return_value = mock_doc

            result = ocr._split_pdf_into_pages(pdf_bytes)

        assert result == [pdf_bytes]

    def test_split_pdf_multi_page(self, ocr: YandexVisionOCR) -> None:
        """Multi-page PDF is split into individual page PDFs."""
        pdf_bytes = b"multi page pdf content"
        with patch("fitz.open") as mock_open:
            mock_doc = MagicMock(spec=["page_count", "close"])
            mock_doc.page_count = 2

            # Mock new_doc for each page
            mock_new_doc_1 = MagicMock(spec=["insert_pdf", "tobytes", "close"])
            mock_new_doc_1.tobytes.return_value = b"page1 pdf"
            mock_new_doc_2 = MagicMock(spec=["insert_pdf", "tobytes", "close"])
            mock_new_doc_2.tobytes.return_value = b"page2 pdf"

            mock_open.side_effect = [
                mock_doc,  # first call: open original doc
                mock_new_doc_1,  # second call: new_doc for page 1
                mock_new_doc_2,  # third call: new_doc for page 2
            ]

            result = ocr._split_pdf_into_pages(pdf_bytes)

        assert result == [b"page1 pdf", b"page2 pdf"]
        assert mock_new_doc_1.insert_pdf.called
        assert mock_new_doc_2.insert_pdf.called

    # ── extract_text success ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_text_success_single_page(
        self,
        ocr: YandexVisionOCR,
        mock_single_page_response: dict[str, Any],
    ) -> None:
        """Happy path: single page PDF → recognized text."""
        # Mock IAM token
        iam_response = MagicMock()
        iam_response.json.return_value = {"iamToken": "test-token"}
        iam_response.raise_for_status.return_value = None

        # Mock OCR API
        ocr_response = MagicMock()
        ocr_response.json.return_value = mock_single_page_response
        ocr_response.raise_for_status.return_value = None

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("fitz.open") as mock_open,
        ):
            # Mock fitz: single page
            mock_doc = MagicMock()
            mock_doc.page_count = 1
            mock_open.return_value = mock_doc

            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(side_effect=[iam_response, ocr_response])

            result = await ocr.extract_text(b"fake pdf", "doc_001")

        assert result == "Текст первой страницы"

    @pytest.mark.asyncio
    async def test_extract_text_success_multi_page(
        self,
        ocr: YandexVisionOCR,
        mock_multi_page_responses: list[dict[str, Any]],
    ) -> None:
        """Multi-page PDF: each page sent separately, results concatenated."""
        iam_response = MagicMock()
        iam_response.json.return_value = {"iamToken": "test-token"}
        iam_response.raise_for_status.return_value = None

        ocr_response_1 = MagicMock()
        ocr_response_1.json.return_value = mock_multi_page_responses[0]
        ocr_response_1.raise_for_status.return_value = None

        ocr_response_2 = MagicMock()
        ocr_response_2.json.return_value = mock_multi_page_responses[1]
        ocr_response_2.raise_for_status.return_value = None

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("fitz.open") as mock_open,
        ):
            # Mock fitz: 2 pages
            mock_doc = MagicMock()
            mock_doc.page_count = 2
            mock_new_doc_1 = MagicMock()
            mock_new_doc_1.tobytes.return_value = b"page1 pdf"
            mock_new_doc_2 = MagicMock()
            mock_new_doc_2.tobytes.return_value = b"page2 pdf"
            mock_open.side_effect = [
                mock_doc,  # open original
                mock_new_doc_1,  # new_doc page 1
                mock_new_doc_2,  # new_doc page 2
            ]

            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            # IAM token + OCR page 1 + OCR page 2
            mock_client.post = AsyncMock(
                side_effect=[
                    iam_response,
                    ocr_response_1,
                    ocr_response_2,
                ]
            )

            result = await ocr.extract_text(b"fake pdf", "doc_002")

        assert "Текст первой страницы" in result
        assert "Текст второй страницы" in result
        assert result == "Текст первой страницы\n\nТекст второй страницы"

    @pytest.mark.asyncio
    async def test_extract_text_empty_response(self, ocr: YandexVisionOCR) -> None:
        """Empty API response returns empty string."""
        iam_response = MagicMock()
        iam_response.json.return_value = {"iamToken": "test-token"}
        iam_response.raise_for_status.return_value = None

        ocr_response = MagicMock()
        ocr_response.json.return_value = {"result": {"textAnnotation": {"fullText": ""}}}
        ocr_response.raise_for_status.return_value = None

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("fitz.open") as mock_open,
        ):
            mock_doc = MagicMock()
            mock_doc.page_count = 1
            mock_open.return_value = mock_doc

            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(side_effect=[iam_response, ocr_response])

            result = await ocr.extract_text(b"pdf", "doc_empty")

        assert result == ""

    # ── extract_text retry logic ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_text_retry_on_auth_error(self, ocr: YandexVisionOCR) -> None:
        """401/403 triggers token refresh and retry."""
        from httpx import HTTPStatusError, Request

        iam_response = MagicMock()
        iam_response.json.return_value = {"iamToken": "fresh-token"}
        iam_response.raise_for_status.return_value = None

        auth_error_response = MagicMock()
        auth_error_response.status_code = 401
        auth_error_response.raise_for_status.side_effect = HTTPStatusError(
            "Unauthorized",
            request=MagicMock(spec=Request),
            response=auth_error_response,
        )

        success_response = MagicMock()
        success_response.json.return_value = {
            "result": {"textAnnotation": {"fullText": "OK"}},
        }
        success_response.raise_for_status.return_value = None

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("fitz.open") as mock_open,
        ):
            mock_doc = MagicMock()
            mock_doc.page_count = 1
            mock_open.return_value = mock_doc

            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            # IAM call, then OCR fails with 401, then IAM refresh, then OCR succeeds
            mock_client.post = AsyncMock(
                side_effect=[
                    iam_response,  # initial IAM token
                    auth_error_response,  # OCR fails with 401
                    iam_response,  # refreshed IAM token
                    success_response,  # OCR succeeds
                ]
            )

            result = await ocr.extract_text(b"pdf", "doc_auth_retry")

        assert result == "OK"
        assert mock_client.post.call_count == 4

    @pytest.mark.asyncio
    async def test_extract_text_retry_on_server_error(self, ocr: YandexVisionOCR) -> None:
        """5xx errors trigger retry without token refresh."""
        from httpx import HTTPStatusError, Request

        iam_response = MagicMock()
        iam_response.json.return_value = {"iamToken": "test-token"}
        iam_response.raise_for_status.return_value = None

        server_error_response = MagicMock()
        server_error_response.status_code = 503
        server_error_response.raise_for_status.side_effect = HTTPStatusError(
            "Service Unavailable",
            request=MagicMock(spec=Request),
            response=server_error_response,
        )

        success_response = MagicMock()
        success_response.json.return_value = {
            "result": {"textAnnotation": {"fullText": "OK"}},
        }
        success_response.raise_for_status.return_value = None

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("fitz.open") as mock_open,
        ):
            mock_doc = MagicMock()
            mock_doc.page_count = 1
            mock_open.return_value = mock_doc

            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(
                side_effect=[
                    iam_response,  # IAM token
                    server_error_response,  # OCR fails with 503
                    success_response,  # OCR succeeds
                ]
            )

            result = await ocr.extract_text(b"pdf", "doc_503_retry")

        assert result == "OK"
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_extract_text_retry_on_network_error(self, ocr: YandexVisionOCR) -> None:
        """Network errors trigger retry."""
        from httpx import RequestError

        iam_response = MagicMock()
        iam_response.json.return_value = {"iamToken": "test-token"}
        iam_response.raise_for_status.return_value = None

        success_response = MagicMock()
        success_response.json.return_value = {
            "result": {"textAnnotation": {"fullText": "OK"}},
        }
        success_response.raise_for_status.return_value = None

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("fitz.open") as mock_open,
        ):
            mock_doc = MagicMock()
            mock_doc.page_count = 1
            mock_open.return_value = mock_doc

            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(
                side_effect=[
                    iam_response,  # IAM token
                    RequestError("timeout"),  # OCR network error
                    success_response,  # OCR succeeds
                ]
            )

            result = await ocr.extract_text(b"pdf", "doc_net_retry")

        assert result == "OK"

    @pytest.mark.asyncio
    async def test_extract_text_all_retries_exhausted(self, ocr: YandexVisionOCR) -> None:
        """All retries exhausted raises OCRUnavailableError."""
        from httpx import HTTPStatusError, Request

        iam_response = MagicMock()
        iam_response.json.return_value = {"iamToken": "test-token"}
        iam_response.raise_for_status.return_value = None

        server_error_response = MagicMock()
        server_error_response.status_code = 503
        server_error_response.raise_for_status.side_effect = HTTPStatusError(
            "Service Unavailable",
            request=MagicMock(spec=Request),
            response=server_error_response,
        )

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("fitz.open") as mock_open,
            pytest.raises(OCRUnavailableError, match="failed after"),
        ):
            mock_doc = MagicMock()
            mock_doc.page_count = 1
            mock_open.return_value = mock_doc

            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            # IAM token + 3 OCR failures (max retries)
            mock_client.post = AsyncMock(
                side_effect=[
                    iam_response,  # IAM token
                    server_error_response,  # attempt 1
                    server_error_response,  # attempt 2
                    server_error_response,  # attempt 3
                ]
            )

            await ocr.extract_text(b"pdf", "doc_exhausted")

    @pytest.mark.asyncio
    async def test_extract_text_non_retryable_error(self, ocr: YandexVisionOCR) -> None:
        """Non-retryable HTTP error (e.g. 400) raises immediately."""
        from httpx import HTTPStatusError, Request

        iam_response = MagicMock()
        iam_response.json.return_value = {"iamToken": "test-token"}
        iam_response.raise_for_status.return_value = None

        bad_request_response = MagicMock()
        bad_request_response.status_code = 400
        bad_request_response.raise_for_status.side_effect = HTTPStatusError(
            "Bad Request",
            request=MagicMock(spec=Request),
            response=bad_request_response,
        )
        bad_request_response.text = "Invalid request"

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("fitz.open") as mock_open,
            pytest.raises(OCRUnavailableError, match="returned HTTP 400"),
        ):
            mock_doc = MagicMock()
            mock_doc.page_count = 1
            mock_open.return_value = mock_doc

            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(
                side_effect=[
                    iam_response,
                    bad_request_response,
                ]
            )

            await ocr.extract_text(b"pdf", "doc_400")

    # ── _parse_response ───────────────────────────────────────────

    def test_parse_response_full(self, ocr: YandexVisionOCR) -> None:
        """Parse single-page response correctly."""
        response: dict[str, Any] = {
            "result": {
                "textAnnotation": {"fullText": "Page 1 text"},
            },
        }

        result = ocr._parse_response(response)

        assert result == "Page 1 text"

    def test_parse_response_empty(self, ocr: YandexVisionOCR) -> None:
        """Empty result returns empty string."""
        assert ocr._parse_response({"result": {"textAnnotation": {"fullText": ""}}}) == ""

    def test_parse_response_missing_fields(self, ocr: YandexVisionOCR) -> None:
        """Missing textAnnotation fields are handled gracefully."""
        response: dict[str, Any] = {
            "result": {
                "textAnnotation": {"fullText": None},
            },
        }

        result = ocr._parse_response(response)

        assert result == ""

    def test_parse_response_no_result_key(self, ocr: YandexVisionOCR) -> None:
        """Response without 'result' key returns empty string."""
        assert ocr._parse_response({}) == ""

    def test_is_ocr_provider(self, ocr: YandexVisionOCR) -> None:
        """YandexVisionOCR satisfies the OCRProvider protocol."""
        assert isinstance(ocr, OCRProvider)


# ======================================================================
#  OCRProvider Protocol — contract test
# ======================================================================


class TestOCRProviderProtocol:
    """Verify that all OCR providers satisfy the OCRProvider protocol.

    This is a structural subtyping check — any class with the right
    async extract_text method signature satisfies the protocol.
    """

    @pytest.mark.parametrize(
        "provider",
        [
            StubOCR(),
            TesseractOCR(),
            YandexVisionOCR(
                ya_key_secret="test-key-for-protocol-check",
                ya_folder_id="test-folder-for-protocol-check",
            ),
        ],
    )
    def test_all_providers_satisfy_protocol(self, provider: object) -> None:
        """All OCR providers are structurally compatible with OCRProvider."""
        assert isinstance(provider, OCRProvider), (
            f"{type(provider).__name__} does not satisfy OCRProvider protocol"
        )

    @pytest.mark.parametrize(
        "provider_cls, kwargs",
        [
            (StubOCR, {}),
            (TesseractOCR, {}),
            (
                YandexVisionOCR,
                {
                    "ya_key_secret": "dummy-key-for-signature-check",
                    "ya_folder_id": "dummy-folder-for-signature-check",
                },
            ),
        ],
    )
    def test_all_providers_have_extract_text_signature(
        self,
        provider_cls: type,
        kwargs: dict[str, Any],
    ) -> None:
        """All providers have async extract_text(pdf_bytes, document_id)."""
        import inspect

        provider = provider_cls(**kwargs)
        method = getattr(provider, "extract_text", None)
        assert method is not None, f"{provider_cls.__name__} missing extract_text"

        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        assert "pdf_bytes" in params, f"{provider_cls.__name__}.extract_text missing pdf_bytes"
        assert "document_id" in params, f"{provider_cls.__name__}.extract_text missing document_id"

        # Verify it's a coroutine (async def)
        assert inspect.iscoroutinefunction(method), (
            f"{provider_cls.__name__}.extract_text is not async"
        )
