"""TesseractOCR — локальный OCR через Tesseract (CPU fallback).

Использует pytesseract для распознавания текста из PDF-файлов.
Работает полностью локально, без внешних API-запросов.

Требует установленного Tesseract OCR на системе:
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- Linux: apt-get install tesseract-ocr tesseract-ocr-rus
- macOS: brew install tesseract

Конфигурация (через .env):
- OCR_TESSERACT_LANG — язык распознавания (default: rus)
- OCR_TESSERACT_TIMEOUT — таймаут на страницу в секундах (default: 30)
"""

from __future__ import annotations

from core.api.app_config import get_config
from core.errors import OCRQualityError, OCRUnavailableError
from core.observability.logger import get_logger

logger = get_logger(__name__)

# Default Tesseract language
_DEFAULT_LANG = "rus"
# Default timeout per page in seconds
_DEFAULT_TIMEOUT = 30.0
# Minimum acceptable text length (below this = quality issue)
_MIN_TEXT_LENGTH = 20


class TesseractOCR:
    """OCR-провайдер на основе Tesseract (локальный, CPU).

    Args:
        lang: Язык распознавания (по умолчанию 'rus').
        timeout: Таймаут на страницу в секундах.
    """

    def __init__(
        self,
        lang: str = _DEFAULT_LANG,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._lang = lang
        self._timeout = timeout

    @classmethod
    def from_config(cls) -> TesseractOCR:
        """Create TesseractOCR from global AppConfig.

        Reads lang and timeout from config.yaml (ocr.tesseract).
        """
        cfg = get_config()
        return cls(
            lang=cfg.ocr.tesseract_lang,
            timeout=cfg.ocr.tesseract_timeout,
        )

    async def extract_text(self, pdf_bytes: bytes, document_id: str) -> str:
        """Extract text from PDF bytes using Tesseract OCR.

        Converts PDF pages to images via pdf2image, then runs Tesseract
        on each page.

        Args:
            pdf_bytes: Raw PDF content (scanned document).
            document_id: Document identifier for logging.

        Returns:
            Extracted text from all pages, concatenated.

        Raises:
            OCRUnavailableError: Tesseract is not installed or unavailable.
            OCRQualityError: Extracted text quality is too low.
        """
        try:
            import pytesseract
            from pdf2image import convert_from_bytes
            from PIL import Image
        except ImportError as e:
            raise OCRUnavailableError(
                f"Missing OCR dependency: {e}. Install: pip install pytesseract pdf2image Pillow"
            ) from e

        try:
            # Convert PDF to images
            images: list[Image.Image] = convert_from_bytes(
                pdf_bytes,
                timeout=int(self._timeout),
            )
        except Exception as e:
            raise OCRUnavailableError(f"Failed to convert PDF to images: {e}") from e

        if not images:
            raise OCRQualityError(f"PDF '{document_id}' has no pages after conversion")

        pages_text: list[str] = []
        for page_num, image in enumerate(images, start=1):
            try:
                text = pytesseract.image_to_string(
                    image,
                    lang=self._lang,
                    timeout=self._timeout,
                )
                if text.strip():
                    pages_text.append(text.strip())
                logger.debug(
                    "Tesseract OCR page processed",
                    extra={
                        "document_id": document_id,
                        "page": page_num,
                        "text_length": len(text),
                    },
                )
            except RuntimeError as e:
                raise OCRUnavailableError(
                    f"Tesseract OCR failed on page {page_num}: {e}. "
                    f"Ensure Tesseract is installed and '{self._lang}' language pack is available."
                ) from e

        full_text = "\n\n".join(pages_text)

        if len(full_text.strip()) < _MIN_TEXT_LENGTH:
            raise OCRQualityError(
                f"OCR quality too low for '{document_id}': "
                f"only {len(full_text.strip())} characters extracted "
                f"(minimum {_MIN_TEXT_LENGTH})"
            )

        logger.info(
            "OCR completed via Tesseract",
            extra={
                "document_id": document_id,
                "pages": len(images),
                "text_length": len(full_text),
            },
        )
        return full_text


__all__ = [
    "TesseractOCR",
]
