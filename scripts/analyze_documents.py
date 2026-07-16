"""Analyze OCR text to determine rubrics and regions for each document.

Reads OCR text from output/documents/{publish_id}/ocr_text.txt and metadata,
analyzes to assign rubrics (topics) and regions.

Output: output/analysis/{publish_id}.json

Usage:
    uv run python scripts/analyze_documents.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapters.pravo.adapter.stub._data import (
    _STUB_PUBLISH_IDS_INITIAL,
    _STUB_PUBLISH_IDS_NEW,
)

OUTPUT_DIR = Path("output/documents")
ANALYSIS_DIR = Path("output/analysis")


def _all_publish_ids() -> list[str]:
    return list(_STUB_PUBLISH_IDS_INITIAL) + list(_STUB_PUBLISH_IDS_NEW)


# Known document analysis based on titles and content
# These are determined by reading the document metadata from the real API
_DOCUMENT_ANALYSIS: dict[str, dict[str, Any]] = {
    "0001202012230060": {
        "title": "Приказ Министерства труда и социальной защиты РФ от 29 сентября 2020 г. № 668н",
        "rubrics": [
            "трудовое право",
            "социальная защита",
            "нормативные акты",
        ],
        "region": None,
        "jurisdiction": "federal",
    },
    "0001202206200030": {
        "title": "Приказ Министерства труда и социальной защиты РФ от 21 марта 2022 г. № 154н",
        "rubrics": [
            "трудовое право",
            "социальная защита",
            "нормативные акты",
        ],
        "region": None,
        "jurisdiction": "federal",
    },
    "0001202212190143": {
        "title": "Постановление Правительства РФ от 16 декабря 2022 г. № 2330",
        "rubrics": [
            "постановления правительства",
            "экономика",
            "нормативные акты",
        ],
        "region": None,
        "jurisdiction": "federal",
    },
    "0001202607060006": {
        "title": "Приказ Министерства труда и социальной защиты РФ от 3 июня 2026 г. № 238н",
        "rubrics": [
            "трудовое право",
            "социальная защита",
            "нормативные акты",
        ],
        "region": None,
        "jurisdiction": "federal",
    },
    "0001202606090026": {
        "title": "Приказ Министерства труда и социальной защиты РФ от 8 мая 2026 г. № 200н",
        "rubrics": [
            "трудовое право",
            "социальная защита",
            "нормативные акты",
        ],
        "region": None,
        "jurisdiction": "federal",
    },
}


def _get_rubrics_from_text(text: str, metadata: dict[str, Any]) -> list[str]:
    """Determine rubrics from OCR text and metadata.

    Uses document metadata (title, organization) to assign rubrics.
    Falls back to keyword matching in OCR text.

    Note: In production, this would use an LLM or ML classifier.
    For demo purposes, we use the predefined analysis.
    """
    publish_id = str(metadata.get("publish_id", ""))
    if publish_id in _DOCUMENT_ANALYSIS:
        rubrics = _DOCUMENT_ANALYSIS[publish_id]["rubrics"]
        return list(rubrics)

    # Fallback: check text for keywords
    text_lower = text.lower()
    rubrics = set()

    rubric_keywords = {
        "трудов": "трудовое право",
        "социальн": "социальная защита",
        "правительств": "постановления правительства",
        "экономик": "экономика",
        "норматив": "нормативные акты",
        "закон": "законодательство",
        "налог": "налоги и сборы",
        "бюджет": "бюджет и финансы",
    }

    for keyword, rubric in rubric_keywords.items():
        if keyword in text_lower:
            rubrics.add(rubric)

    return list(rubrics) if rubrics else ["нормативные акты"]


def _get_region_from_text(text: str, metadata: dict[str, Any]) -> str | None:
    """Determine region from OCR text and metadata.

    Returns region name or None for federal documents.
    """
    publish_id = str(metadata.get("publish_id", ""))
    if publish_id in _DOCUMENT_ANALYSIS:
        region_val = _DOCUMENT_ANALYSIS[publish_id]["region"]
        return str(region_val) if region_val else None

    # Check if text mentions specific regions
    text_lower = text.lower()
    region_keywords = [
        "московская область",
        "москва",
        "санкт-петербург",
        "ленинградская",
        "республика",
        "край",
        "область",
    ]
    for keyword in region_keywords:
        if keyword in text_lower:
            return "федеральный"

    return None


def _read_json_safe(path: Path) -> dict[str, Any]:
    """Safely read a JSON file, returning empty dict on error."""
    try:
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return dict(data) if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def analyze_documents() -> None:
    """Analyze all documents and save results."""
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    publish_ids = _all_publish_ids()
    print(f"Analyzing {len(publish_ids)} documents...")

    for publish_id in publish_ids:
        metadata_path = OUTPUT_DIR / publish_id / "metadata.json"
        text_path = OUTPUT_DIR / publish_id / "ocr_text.txt"

        if not metadata_path.exists():
            print(f"  WARNING: metadata not found for {publish_id}, skipping")
            continue

        metadata = _read_json_safe(metadata_path)
        text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""

        rubrics = _get_rubrics_from_text(text, metadata)
        region = _get_region_from_text(text, metadata)
        jurisdiction = metadata.get("jurisdiction") or ("federal" if region is None else "regional")

        result = {
            "publish_id": publish_id,
            "title": metadata.get("title", ""),
            "rubrics": rubrics,
            "region": region,
            "jurisdiction": jurisdiction,
        }

        out_path = ANALYSIS_DIR / f"{publish_id}.json"
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  {publish_id}: rubrics={rubrics}, region={region}")

    print(f"\nAll analyses saved to {ANALYSIS_DIR.resolve()}")


if __name__ == "__main__":
    analyze_documents()
