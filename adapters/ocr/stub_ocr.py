"""StubOCR — заглушка OCR для тестов и демонстрации.

Возвращает предопределённый текст для известных document_id.
Не требует внешних сервисов или установки Tesseract.

Используется:
- В тестах (unit-тесты OCR-пайплайна)
- В stub-режиме PravoAdapter (демонстрация без внешних зависимостей)
"""

from __future__ import annotations

from core.errors import InvalidInputError
from core.observability.logger import get_logger

logger = get_logger(__name__)

# Предопределённые тексты для известных document_id (eo_number).
# Ключ — eo_number документа, значение — фиктивный текст.
_STUB_TEXTS: dict[str, str] = {
    "0001202012230060": (
        "ПРИКАЗ\n"
        "Министерства труда и социальной защиты Российской Федерации\n"
        "от 29 сентября 2020 г. № 668н\n\n"
        "Об утверждении Порядка предоставления сведений о доходах, расходах, "
        "об имуществе и обязательствах имущественного характера\n\n"
        "В соответствии с Федеральным законом от 25 декабря 2008 года № 273-ФЗ "
        "«О противодействии коррупции» приказываю:\n\n"
        "1. Утвердить прилагаемый Порядок предоставления сведений о доходах, "
        "расходах, об имуществе и обязательствах имущественного характера.\n\n"
        "2. Настоящий приказ вступает в силу с 1 января 2021 года."
    ),
    "0001202206200030": (
        "ПРИКАЗ\n"
        "Министерства труда и социальной защиты Российской Федерации\n"
        "от 21 марта 2022 г. № 154н\n\n"
        "Об утверждении профессионального стандарта «Специалист по управлению "
        "персоналом»\n\n"
        "В соответствии с пунктом 16 Правил разработки и утверждения "
        "профессиональных стандартов приказываю:\n\n"
        "1. Утвердить прилагаемый профессиональный стандарт «Специалист по "
        "управлению персоналом».\n\n"
        "2. Установить, что настоящий приказ вступает в силу с 1 сентября 2022 года."
    ),
    "0001202212190143": (
        "ПОСТАНОВЛЕНИЕ\n"
        "Правительства Российской Федерации\n"
        "от 16 декабря 2022 г. № 2330\n\n"
        "О порядке предоставления государственных гарантий Российской Федерации\n\n"
        "В соответствии со статьей 116 Бюджетного кодекса Российской Федерации "
        "Правительство Российской Федерации постановляет:\n\n"
        "1. Утвердить прилагаемые Правила предоставления государственных гарантий "
        "Российской Федерации.\n\n"
        "2. Настоящее постановление вступает в силу со дня его официального опубликования."
    ),
}

# Текст для неизвестных document_id
_DEFAULT_TEXT = (
    "Stub OCR text for document {document_id}. This is a placeholder for testing purposes."
)


class StubOCR:
    """Заглушка OCR для тестов и демонстрации.

    Возвращает предопределённый текст для известных document_id.
    Для неизвестных возвращает шаблонный текст с указанием document_id.
    """

    async def extract_text(self, pdf_bytes: bytes, document_id: str) -> str:
        """Return stub text for the given document_id.

        Args:
            pdf_bytes: Ignored (stub does not process PDFs).
            document_id: Document identifier. If known, returns predefined text.

        Returns:
            Predefined or template text.

        Raises:
            OCRUnavailableError: Never raised by stub (always available).
        """
        if not pdf_bytes:
            raise InvalidInputError("pdf_bytes can't be empty")

        text = _STUB_TEXTS.get(document_id)
        if text is not None:
            logger.info(
                "Stub OCR: returning predefined text",
                extra={"document_id": document_id, "text_length": len(text)},
            )
            return text

        text = _DEFAULT_TEXT.format(document_id=document_id)
        logger.warning(
            "Stub OCR: unknown document_id, returning template text",
            extra={"document_id": document_id},
        )
        return text


__all__ = [
    "StubOCR",
]
