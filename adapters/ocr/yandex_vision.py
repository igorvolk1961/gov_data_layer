"""YandexVisionOCR — OCR через Yandex Cloud OCR API.

Использует Yandex OCR API v1 (recognizeText) для распознавания текста
из PDF-файлов (скан-копий официальных документов).

Документация API:
https://yandex.cloud/ru/docs/ocr/api-ref/OCR/recognizeText

Конфигурация:
- ya_key_secret — секретный ключ сервисного аккаунта или API-ключ (из .env)
- ya_folder_id — ID каталога в Yandex Cloud (из config.yaml или .env)
- timeout — таймаут запроса (из config.yaml)
"""

from __future__ import annotations

import base64
from typing import Any

import fitz  # PyMuPDF
import httpx

from core.api.app_config import get_config
from core.errors import OCRUnavailableError
from core.observability.logger import get_logger

logger = get_logger(__name__)

# Yandex OCR API endpoint
_OCR_API_URL = "https://ai.api.cloud.yandex.net/ocr/v1/recognizeText"
_IAM_TOKEN_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"

# Default timeout for OCR requests (PDFs can be large)
_DEFAULT_TIMEOUT = 120.0
# Max retries for transient failures
_MAX_RETRIES = 3
# Yandex OCR API limit: max 1 page per request
_MAX_PAGES_PER_REQUEST = 1


class YandexVisionOCR:
    """OCR-провайдер на основе Yandex Cloud OCR API.

    Поддерживает два способа аутентификации:
    1. API-ключ (начинается с AQVN) — используется напрямую.
    2. Сервисный аккаунт (JWT-токен) — получает IAM-токен.

    API имеет ограничение: не более 1 страницы за запрос.
    Многостраничные PDF разбиваются на отдельные страницы,
    каждая отправляется отдельным запросом.

    Args:
        ya_key_secret: Секретный ключ сервисного аккаунта (JWT) или API-ключ.
        ya_folder_id: ID каталога Yandex Cloud.
        timeout: Таймаут HTTP-запроса в секундах.
    """

    def __init__(
        self,
        ya_key_secret: str,
        ya_folder_id: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._key_secret = ya_key_secret
        self._folder_id = ya_folder_id
        self._timeout = timeout
        self._iam_token: str | None = None
        # If secret starts with AQVN - it's an API key, use directly
        self._is_api_key = ya_key_secret.strip().startswith("AQVN") if ya_key_secret else False

    @classmethod
    def from_config(cls) -> YandexVisionOCR:
        """Create YandexVisionOCR from global AppConfig.

        Reads ya_key_secret from .env (OCR_YA_KEY_SECRET),
        ya_folder_id and timeout from config.yaml (ocr.yandex_vision).
        """
        cfg = get_config()
        ya_key_secret = cfg.ocr.ya_folder_id  # placeholder, real secret from .env
        # Actually read secret from env directly (it's not in AppConfig for security)
        import os

        ya_key_secret = os.environ.get("OCR_YA_KEY_SECRET", "")
        return cls(
            ya_key_secret=ya_key_secret,
            ya_folder_id=cfg.ocr.ya_folder_id,
            timeout=cfg.ocr.yandex_vision_timeout,
        )

    async def _get_authorization_header(self) -> str:
        """Получить значение заголовка Authorization.

        Для API-ключа: "Api-Key <key>"
        Для сервисного аккаунта: "Bearer <iam_token>"

        Returns:
            Значение для заголовка Authorization.
        """
        if self._is_api_key:
            return f"Api-Key {self._key_secret.strip()}"

        if self._iam_token:
            return f"Bearer {self._iam_token}"

        # Получаем IAM-токен
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    _IAM_TOKEN_URL,
                    json={"jwt": self._key_secret},
                )
                response.raise_for_status()
                data = response.json()
                self._iam_token = data["iamToken"]
                return f"Bearer {self._iam_token}"
            except httpx.HTTPStatusError as e:
                raise OCRUnavailableError(
                    f"Failed to get IAM token: HTTP {e.response.status_code}"
                ) from e
            except httpx.RequestError as e:
                raise OCRUnavailableError(f"Failed to get IAM token: network error: {e}") from e
            except (KeyError, ValueError) as e:
                raise OCRUnavailableError(f"Failed to parse IAM token response: {e}") from e

    async def extract_text(self, pdf_bytes: bytes, document_id: str) -> str:
        """Extract text from PDF bytes using Yandex Cloud OCR API.

        Многостраничные PDF разбиваются на отдельные страницы,
        каждая отправляется отдельным запросом (лимит API: 1 страница).

        Args:
            pdf_bytes: Raw PDF content (scanned document).
            document_id: Document identifier for logging.

        Returns:
            Extracted text from all pages, concatenated.

        Raises:
            OCRUnavailableError: Yandex OCR API is unavailable.
        """
        auth_header = await self._get_authorization_header()

        # Разбиваем PDF на отдельные страницы
        page_pdfs = self._split_pdf_into_pages(pdf_bytes)

        all_text_parts: list[str] = []
        for page_num, page_pdf_bytes in enumerate(page_pdfs, start=1):
            page_text = await self._recognize_page(
                page_pdf_bytes=page_pdf_bytes,
                page_num=page_num,
                document_id=document_id,
                auth_header=auth_header,
            )
            if page_text.strip():
                all_text_parts.append(page_text)

        full_text = "\n\n".join(all_text_parts)
        logger.info(
            "OCR completed via Yandex OCR API",
            extra={
                "document_id": document_id,
                "pages": len(page_pdfs),
                "text_length": len(full_text),
            },
        )
        return full_text

    def _split_pdf_into_pages(self, pdf_bytes: bytes) -> list[bytes]:
        """Разбить PDF на отдельные страницы.

        Args:
            pdf_bytes: Содержимое многостраничного PDF.

        Returns:
            Список PDF-байтов, по одному на страницу.
        """
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            num_pages = doc.page_count
            if num_pages <= 1:
                return [pdf_bytes]

            page_pdfs: list[bytes] = []
            for page_num in range(num_pages):
                new_doc = fitz.open()
                try:
                    new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                    page_pdfs.append(new_doc.tobytes())
                finally:
                    new_doc.close()
            return page_pdfs
        finally:
            doc.close()

    async def _recognize_page(
        self,
        page_pdf_bytes: bytes,
        page_num: int,
        document_id: str,
        auth_header: str,
    ) -> str:
        """Распознать текст одной страницы PDF через Yandex OCR API.

        Args:
            page_pdf_bytes: PDF-байты одной страницы.
            page_num: Номер страницы (для логирования).
            document_id: ID документа (для логирования).
            auth_header: Значение заголовка Authorization.

        Returns:
            Распознанный текст страницы.

        Raises:
            OCRUnavailableError: API недоступен.
        """
        pdf_base64 = base64.b64encode(page_pdf_bytes).decode("utf-8")

        request_body: dict[str, Any] = {
            "mimeType": "application/pdf",
            "languageCodes": ["*"],
            "model": "page",
            "content": pdf_base64,
        }

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "x-folder-id": self._folder_id,
            "x-data-logging-enabled": "true",
        }

        last_error: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        _OCR_API_URL,
                        headers=headers,
                        json=request_body,
                    )
                    response.raise_for_status()
                    result = response.json()
                    return self._parse_response(result)

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(
                    "Yandex OCR API attempt failed",
                    extra={
                        "document_id": document_id,
                        "page": page_num,
                        "attempt": attempt,
                        "status_code": e.response.status_code,
                    },
                )
                if e.response.status_code in (401, 403):
                    if self._is_api_key:
                        raise OCRUnavailableError(
                            f"Yandex OCR API auth failed: HTTP {e.response.status_code}. "
                            "Check OCR_YA_KEY_SECRET (API key)."
                        ) from e
                    # Auth error for service account — refresh token and retry
                    self._iam_token = None
                    auth_header = await self._get_authorization_header()
                    headers["Authorization"] = auth_header
                    continue
                if e.response.status_code in (429, 500, 502, 503):
                    # Rate limit or server error — retry
                    continue
                raise OCRUnavailableError(
                    f"Yandex OCR API returned HTTP {e.response.status_code}: "
                    f"{e.response.text[:200]}"
                ) from e

            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    "Yandex OCR API network error",
                    extra={
                        "document_id": document_id,
                        "page": page_num,
                        "attempt": attempt,
                        "error": str(e),
                    },
                )
                continue

        raise OCRUnavailableError(
            f"Yandex OCR API failed after {_MAX_RETRIES} attempts: {last_error}"
        ) from last_error

    def _parse_response(self, response: dict[str, Any]) -> str:
        """Parse Yandex OCR API response into plain text.

        Формат ответа Yandex OCR API v1:
        {
            "result": {
                "textAnnotation": {
                    "fullText": "..."
                },
                "blocks": [...]
            }
        }

        Args:
            response: JSON response from recognizeText.

        Returns:
            Распознанный текст страницы.
        """
        try:
            text_annotation = response.get("result", {}).get("textAnnotation", {})
            full_text = (text_annotation.get("fullText") or "").strip()
            return full_text
        except (AttributeError, KeyError, TypeError):
            return ""


__all__ = [
    "YandexVisionOCR",
]
