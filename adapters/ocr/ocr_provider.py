"""OCRProvider Protocol — контракт для всех OCR-провайдеров.

Определяет абстракцию для сменяемого OCR:
- YandexVisionOCR (основной, через Yandex Cloud Vision API)
- TesseractOCR (CPU fallback, через pytesseract)
- StubOCR (для тестов, без внешних зависимостей)

Переключение через config: OCR_PROVIDER=yandex_vision|tesseract|stub
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class OCRProvider(Protocol):
    """Протокол OCR-провайдера.

    Каждая реализация должна уметь извлекать текст из PDF-байтов.
    """

    async def extract_text(self, pdf_bytes: bytes, document_id: str) -> str:
        """Extract text from PDF bytes.

        Args:
            pdf_bytes: Raw PDF content (may be scanned images without text layer).
            document_id: Document identifier for logging/tracing.

        Returns:
            Extracted text content.

        Raises:
            OCRUnavailableError: OCR service is unavailable (network, auth, etc.).
            OCRQualityError: Extracted text quality is below acceptable threshold.
        """
        ...


__all__ = [
    "OCRProvider",
]
