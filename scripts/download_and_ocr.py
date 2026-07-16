"""Download documents from pravo.gov.ru API and run OCR via Yandex Vision.

Processes all 5 stub publish_ids (3 initial + 2 new) and saves:
  - output/documents/{publish_id}/raw.json          — raw API response
  - output/documents/{publish_id}/metadata.json      — parsed metadata
  - output/documents/{publish_id}/document.pdf       — downloaded PDF
  - output/documents/{publish_id}/ocr_text.txt       — OCR text

Usage:
    uv run python scripts/download_and_ocr.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from adapters.pravo.adapter.stub._data import (
    _STUB_PUBLISH_IDS_INITIAL,
    _STUB_PUBLISH_IDS_NEW,
)
from adapters.pravo.pravo_client import PravoClient
from adapters.pravo.pravo_parser import PravoParser

OUTPUT_DIR = Path("output/documents")


def _all_publish_ids() -> list[str]:
    """Return all 5 publish_ids (initial + new)."""
    return list(_STUB_PUBLISH_IDS_INITIAL) + list(_STUB_PUBLISH_IDS_NEW)


async def download_and_ocr() -> None:
    """Main entry point: download all documents and OCR them."""
    # Determine OCR provider
    ocr_provider = None
    try:
        from adapters.ocr.yandex_vision import YandexVisionOCR
        from core.api.app_config import get_config

        cfg = get_config()
        if cfg.ocr.provider == "yandex_vision":
            ocr_provider = YandexVisionOCR.from_config()
            print(f"Using Yandex Vision OCR (folder: {ocr_provider._folder_id})")
        elif cfg.ocr.provider == "stub":
            print("OCR provider is 'stub' — will use summary text instead of OCR")
        else:
            print(f"OCR provider: {cfg.ocr.provider}")
    except Exception as e:
        print(f"Could not determine OCR provider: {e}")
        print("Will try Yandex Vision from env vars...")
        try:
            from adapters.ocr.yandex_vision import YandexVisionOCR

            ocr_provider = YandexVisionOCR.from_config()
        except Exception:
            print("Yandex Vision not configured; will use document summary as text")

    client = PravoClient()
    parser = PravoParser()

    publish_ids = _all_publish_ids()
    print(f"Processing {len(publish_ids)} documents: {publish_ids}")

    for publish_id in publish_ids:
        doc_dir = OUTPUT_DIR / publish_id
        doc_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'=' * 60}")
        print(f"Processing: {publish_id}")
        print(f"{'=' * 60}")

        # 1. Fetch raw document from API
        raw_path = doc_dir / "raw.json"
        if raw_path.exists():
            print(f"  Raw data already exists at {raw_path}, skipping fetch")
            with open(raw_path, encoding="utf-8") as f:
                raw = json.load(f)
        else:
            print("  Fetching document from pravo.gov.ru...")
            raw = await client.get_document(publish_id)
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2, default=str)
            print(f"  Saved raw data to {raw_path}")

        # 2. Parse document
        metadata_path = doc_dir / "metadata.json"
        if metadata_path.exists():
            print(f"  Metadata already exists at {metadata_path}")
        else:
            try:
                doc = parser.parse_document(raw)
                meta = {
                    "id": doc.id,
                    "publish_id": doc.publish_id,
                    "title": doc.title,
                    "document_number": doc.document_number,
                    "summary": doc.summary,
                    "url": doc.url,
                    "jurisdiction": doc.jurisdiction,
                    "region": doc.region,
                    "organization_id": doc.organization_id,
                    "organization": doc.organization,
                    "document_type_id": doc.document_type_id,
                    "document_type": doc.document_type,
                    "topic": doc.topic,
                    "valid_from": doc.valid_from.isoformat() if doc.valid_from else None,
                    "publish_date": doc.publish_date.isoformat() if doc.publish_date else None,
                    "meta": {k: str(v) for k, v in doc.meta.items()},
                }
                with open(metadata_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                print(f"  Saved metadata to {metadata_path}")
            except Exception as e:
                print(f"  ERROR parsing document: {e}")
                continue

        # 3. Download PDF
        pdf_path = doc_dir / "document.pdf"
        if pdf_path.exists():
            print(f"  PDF already exists at {pdf_path}")
        else:
            pdf_url = raw.get("pdfUrl") or (raw.get("meta") or {}).get("pdf_url")
            if pdf_url:
                try:
                    import httpx

                    async with httpx.AsyncClient(timeout=120.0) as http:
                        print(f"  Downloading PDF from {pdf_url}...")
                        resp = await http.get(pdf_url)
                        resp.raise_for_status()
                        pdf_path.write_bytes(resp.content)
                        print(f"  Saved PDF ({len(resp.content)} bytes)")
                except Exception as e:
                    print(f"  ERROR downloading PDF: {e}")
            else:
                print("  No PDF URL available in API response")

        # 4. Extract text (OCR or summary)
        text_path = doc_dir / "ocr_text.txt"
        if text_path.exists():
            print(f"  OCR text already exists at {text_path}")
        else:
            text = ""
            if ocr_provider and pdf_path.exists():
                try:
                    print("  Running OCR via Yandex Vision...")
                    pdf_bytes = pdf_path.read_bytes()
                    text = await ocr_provider.extract_text(pdf_bytes, publish_id)
                    print(f"  OCR complete: {len(text)} chars")
                except Exception as e:
                    print(f"  OCR failed: {e}")
                    text = ""

            if not text:
                print("  Using document summary as text fallback")
                text = doc.summary or ""

            text_path.write_text(text, encoding="utf-8")
            print(f"  Saved text ({len(text)} chars) to {text_path}")

    await client.close()
    print(f"\n{'=' * 60}")
    print(f"All done! Processed {len(publish_ids)} documents.")
    print(f"Output directory: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(download_and_ocr())
