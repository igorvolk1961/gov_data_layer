"""Script to test real PDF recognition via Yandex Vision OCR.

Requires environment variables (in .env or export):
- OCR_YA_KEY_SECRET — Yandex Cloud API key (AQVN...) or service account JWT
- OCR_YA_FOLDER_ID — Yandex Cloud folder ID

Usage:
    uv run python scripts/test_yandex_vision.py path/to/document.pdf
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing project modules so env vars are available
load_dotenv()

from adapters.ocr.yandex_vision import YandexVisionOCR  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/test_yandex_vision.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    # Read credentials from environment
    ya_key_secret = os.environ.get("OCR_YA_KEY_SECRET")
    ya_folder_id = os.environ.get("OCR_YA_FOLDER_ID")

    if not ya_key_secret or not ya_folder_id:
        print("Error: Missing Yandex Cloud credentials.", file=sys.stderr)
        print("Set OCR_YA_KEY_SECRET, OCR_YA_FOLDER_ID in .env or environment.", file=sys.stderr)
        sys.exit(1)

    # Read PDF file
    pdf_bytes = Path(pdf_path).read_bytes()

    # Initialize Yandex Vision OCR
    ocr = YandexVisionOCR(
        ya_key_secret=ya_key_secret,
        ya_folder_id=ya_folder_id,
        timeout=120.0,
    )

    print(f"Processing: {pdf_path}")
    print(f"PDF size: {len(pdf_bytes)} bytes")
    print("Running OCR via Yandex Vision API...")

    try:
        text = await ocr.extract_text(pdf_bytes, document_id=pdf_path)
        print("\n=== EXTRACTED TEXT ===")
        print(text)
        print(f"\n=== Total chars: {len(text)} ===")

        # Save result to a .txt file next to the source PDF
        pdf_file = Path(pdf_path)
        output_path = pdf_file.with_suffix(".yandex_vision.txt")
        output_path.write_text(text, encoding="utf-8")
        print(f"\nResult saved to: {output_path}")
    except Exception as e:
        print(f"\nOCR failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
