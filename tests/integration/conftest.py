"""Integration tests configuration — loads .env, configures Tesseract path, and initializes observability."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта, чтобы pytest видел OCR_YA_* переменные
load_dotenv(Path(__file__).parents[2] / ".env")

# Инициализируем трейсер (FileFallbackTracer) для тестов, которые используют tracer
from core.observability import configure  # noqa: E402

configure()

# Путь к Tesseract: из переменной окружения TESSERACT_CMD или стандартный для платформы
_tesseract_path = os.environ.get("TESSERACT_CMD")
if not _tesseract_path:
    if sys.platform == "win32":
        _tesseract_path = r"D:\Program Files\Tesseract-OCR\tesseract.exe"
    else:
        _tesseract_path = "/usr/bin/tesseract"

if os.path.exists(_tesseract_path):
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = _tesseract_path
