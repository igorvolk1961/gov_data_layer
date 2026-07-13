"""Integration tests configuration — loads .env and configures Tesseract path."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта, чтобы pytest видел OCR_YA_* переменные
load_dotenv(Path(__file__).parents[2] / ".env")

# Указываем путь к Tesseract, если он не в PATH
# Windows: D:\Program Files\Tesseract-OCR\tesseract.exe
# Linux (CI): /usr/bin/tesseract (ставится через apt-get)
if sys.platform == "win32":
    _tesseract_path = r"D:\Program Files\Tesseract-OCR\tesseract.exe"
else:
    _tesseract_path = "/usr/bin/tesseract"

if os.path.exists(_tesseract_path):
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = _tesseract_path
