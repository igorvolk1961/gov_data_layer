"""OCR Provider — абстракция для сменяемого OCR.

Провайдеры:
- YandexVisionOCR — через Yandex Cloud Vision API (основной)
- TesseractOCR — локальный OCR через Tesseract (CPU fallback)
- StubOCR — заглушка для тестов (без внешних зависимостей)

Переключение через config: OCR_PROVIDER=yandex_vision|tesseract|stub
"""

from adapters.ocr.ocr_provider import OCRProvider
from adapters.ocr.stub_ocr import StubOCR
from adapters.ocr.tesseract_ocr import TesseractOCR
from adapters.ocr.yandex_vision import YandexVisionOCR

__all__ = [
    "OCRProvider",
    "StubOCR",
    "TesseractOCR",
    "YandexVisionOCR",
]
