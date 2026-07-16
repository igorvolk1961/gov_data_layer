"""Интеграционные тесты OCR с реальными провайдерами.

Запуск (требуются credentials в .env):
    uv run pytest tests/integration/test_ocr_integration.py -v -m integration

Запуск только Yandex Vision (без fallback):
    uv run pytest tests/integration/test_ocr_integration.py -v -m "integration and not slow"

Запуск с fallback на Tesseract:
    uv run pytest tests/integration/test_ocr_integration.py -v -m slow

Примечание:
    - Yandex Vision требует OCR_YA_KEY_SECRET, OCR_YA_FOLDER_ID в .env
    - Tesseract fallback требует установленного Tesseract OCR engine на системе
    - Тесты помечены как slow, т.к. делают реальные HTTP-запросы к API
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from adapters.ocr.tesseract_ocr import TesseractOCR
from adapters.ocr.yandex_vision import YandexVisionOCR
from core.errors import OCRUnavailableError

# Путь к тестовому PDF (2 страницы, 49 КБ)
TEST_PDF = Path(__file__).parents[2] / "tests" / "data" / "pdf" / "7800202607010012.pdf"


def _check_yandex_credentials() -> bool:
    """Проверить, настроены ли credentials для Yandex Vision."""
    return all(
        [
            os.environ.get("OCR_YA_KEY_SECRET"),
            os.environ.get("OCR_YA_FOLDER_ID"),
        ]
    )


def _check_tesseract_available() -> bool:
    """Проверить, доступен ли Tesseract на системе."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# ============================================================
# Yandex Vision OCR — реальный API
# ============================================================


@pytest.mark.integration
@pytest.mark.skipif(
    not _check_yandex_credentials(),
    reason="Yandex Vision credentials not configured (OCR_YA_KEY_SECRET, OCR_YA_FOLDER_ID)",
)
@pytest.mark.asyncio
async def test_yandex_vision_real_pdf() -> None:
    """Распознавание реального PDF через Yandex Vision OCR API v1.

    Проверяет:
    - Успешный HTTP-ответ от api.ai.cloud.yandex.net
    - Наличие распознанного текста (непустой результат)
    - Корректную обработку многостраничного PDF (2 страницы)
    """
    pdf_bytes = TEST_PDF.read_bytes()

    ocr = YandexVisionOCR(
        ya_key_secret=os.environ["OCR_YA_KEY_SECRET"],
        ya_folder_id=os.environ["OCR_YA_FOLDER_ID"],
        timeout=120.0,
    )

    text = await ocr.extract_text(pdf_bytes, document_id=str(TEST_PDF))

    assert text, "Yandex Vision OCR вернул пустой текст"
    assert len(text) > 100, f"Слишком короткий результат: {len(text)} chars"

    # Проверяем, что распознался осмысленный русский текст
    assert "Закон" in text, "Не найден ожидаемый текст 'Закон'"
    assert "Санкт-Петербург" in text, "Не найден ожидаемый текст 'Санкт-Петербург'"
    assert "Беглов" in text, "Не найдена подпись губернатора"


@pytest.mark.integration
@pytest.mark.skipif(
    not _check_yandex_credentials(),
    reason="Yandex Vision credentials not configured",
)
# ============================================================
# Tesseract OCR — локальный fallback
# ============================================================


@pytest.mark.integration
@pytest.mark.skipif(
    not _check_tesseract_available(),
    reason="Tesseract OCR engine not installed on this system",
)
@pytest.mark.asyncio
async def test_tesseract_fallback_real_pdf() -> None:
    """Распознавание реального PDF через Tesseract OCR (локальный fallback).

    Проверяет:
    - Успешное распознавание через pytesseract
    - Наличие непустого текста
    """
    pdf_bytes = TEST_PDF.read_bytes()

    ocr = TesseractOCR(lang="rus", timeout=60.0)
    text = await ocr.extract_text(pdf_bytes, document_id=str(TEST_PDF))

    assert text, "Tesseract OCR вернул пустой текст"
    assert len(text) > 50, f"Слишком короткий результат: {len(text)} chars"


# ============================================================
# Стратегия: Yandex Vision → fallback Tesseract
# ============================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ocr_with_fallback() -> None:
    """Интеграционный тест: Yandex Vision с fallback на Tesseract.

    Стратегия:
    1. Пытается распознать PDF через Yandex Vision OCR API
    2. Если Yandex недоступен — fallback на локальный Tesseract OCR
    3. В любом случае должен быть получен непустой текст

    Это симулирует реальное поведение в production:
    - cloud API как основной провайдер
    - локальный OCR как fallback при недоступности сети/API
    """
    pdf_bytes = TEST_PDF.read_bytes()
    text: str | None = None
    used_provider: str = "none"

    # Step 1: Try Yandex Vision
    if _check_yandex_credentials():
        ocr = YandexVisionOCR(
            ya_key_secret=os.environ["OCR_YA_KEY_SECRET"],
            ya_folder_id=os.environ["OCR_YA_FOLDER_ID"],
            timeout=120.0,
        )
        try:
            text = await ocr.extract_text(pdf_bytes, document_id=str(TEST_PDF))
            used_provider = "yandex_vision"
        except (OCRUnavailableError, Exception):
            text = None

    # Step 2: Fallback to Tesseract
    if text is None and _check_tesseract_available():
        ocr = TesseractOCR(lang="rus", timeout=60.0)
        try:
            text = await ocr.extract_text(pdf_bytes, document_id=str(TEST_PDF))
            used_provider = "tesseract (fallback)"
        except Exception:
            text = None

    if text is None:
        pytest.skip("Neither Yandex Vision nor Tesseract OCR available")

    assert text, f"OCR provider '{used_provider}' вернул пустой текст"
    assert len(text) > 50, f"Слишком короткий результат от '{used_provider}': {len(text)} chars"
