"""DemoDocProvider — OCR-провайдер для демонстрации без внешних сервисов.

Читает заранее распознанные (через Yandex Vision) тексты документов
из файлов fixtures/ocr_results/{publish_id}.txt.

Не требует PDF, Yandex Vision API или Tesseract.
Используется в демо-скриптах (scripts/) для быстрого инжеста
без ожидания реального OCR.
"""

from __future__ import annotations

from pathlib import Path

from core.errors import InvalidInputError, SourceUnavailableError
from core.observability.logger import get_logger

logger = get_logger(__name__)

# Path to OCR results folder: fixtures/ocr_results/
_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "ocr_results"


class DemoDocProvider:
    """OCR-провайдер для демонстрации: читает текст из fixtures/ocr_results/.

    Извлекает publish_id из document_id (формат "pravo-{publish_id}"),
    ищет файл fixtures/ocr_results/{publish_id}.txt и возвращает его
    содержимое. Если файл не найден — выбрасывает SourceUnavailableError.
    """

    async def extract_text(self, pdf_bytes: bytes, document_id: str) -> str:
        """Return document text from fixtures/ocr_results/{publish_id}.txt.

        Args:
            pdf_bytes: Ignored (does not process PDFs).
            document_id: Document identifier (format "pravo-{publish_id}").

        Returns:
            Document text from fixture file.

        Raises:
            InvalidInputError: If pdf_bytes is empty.
            SourceUnavailableError: If fixture file not found.
        """
        if not pdf_bytes:
            raise InvalidInputError("pdf_bytes can't be empty")

        # Extract publish_id from document_id
        publish_id = document_id
        if document_id.startswith("pravo-"):
            publish_id = document_id[len("pravo-") :]

        # Look for fixtures/ocr_results/{publish_id}.txt
        filepath = _FIXTURES_DIR / f"{publish_id}.txt"
        if filepath.exists():
            text = filepath.read_text(encoding="utf-8")
            logger.info(
                "DemoDoc: loaded %d chars from %s",
                len(text),
                filepath.name,
            )
            return text

        # Not found — raise error
        error_msg = (
            f"DemoDocProvider: no OCR fixture for document '{document_id}' (expected at {filepath})"
        )
        logger.error(error_msg)
        raise SourceUnavailableError(error_msg)


__all__ = [
    "DemoDocProvider",
]
