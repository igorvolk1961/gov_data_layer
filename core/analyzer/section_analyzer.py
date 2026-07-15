"""SectionAnalyzer — stub regex-based semantic analysis of document sections.

MVP implementation uses regex patterns to detect common legal fact types.
This is a deliberate stub — full semantic analysis (NER, LLM) is a
non-trivial task beyond the current PoC scope.

Detected patterns:
- REVOKE: "признать утратившим силу", "отменить", "признать не действующим"
- MODIFY: "внести изменения", "изложить в новой редакции", "дополнить"
- ENACT: "ввести в действие", "вступает в силу", "распространяется на"

Each fact includes extraction_confidence based on pattern match quality.
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any


class SectionFactType(str, Enum):
    """Types of legal facts that can be extracted from section text."""

    REVOKE = "revoke"  # Отмена другого документа/раздела
    MODIFY = "modify"  # Изменение другого документа/раздела
    ENACT = "enact"  # Введение в действие
    RELATE = "relate"  # Установление правового отношения
    UNKNOWN = "unknown"  # Неопределённый тип


class SectionFact:
    """A single extracted legal fact from a document section.

    Args:
        fact_type: Type of legal fact detected.
        section_external_id: External ID of the section that contains the fact.
        text: The matched text snippet that triggered detection.
        confidence: Extraction confidence (0.0–1.0).
        target_document_id: Optional referenced document ID (e.g., for REVOKE/MODIFY).
        effective_date: Optional effective date mentioned in the text.
    """

    def __init__(
        self,
        fact_type: SectionFactType,
        section_external_id: str,
        text: str,
        confidence: float = 1.0,
        target_document_id: str | None = None,
        effective_date: date | None = None,
    ) -> None:
        self.fact_type = fact_type
        self.section_external_id = section_external_id
        self.text = text
        self.confidence = confidence
        self.target_document_id = target_document_id
        self.effective_date = effective_date

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage/tracing."""
        return {
            "fact_type": self.fact_type.value,
            "section_external_id": self.section_external_id,
            "text": self.text[:200],
            "confidence": self.confidence,
            "target_document_id": self.target_document_id,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
        }

    def __repr__(self) -> str:
        return (
            f"SectionFact({self.fact_type.value}, "
            f"section={self.section_external_id}, "
            f"confidence={self.confidence:.2f})"
        )


# ── Pattern definitions ──────────────────────────────────────────────
# Each pattern: (regex, fact_type, confidence_weight)
# Higher weight means more specific pattern → higher confidence

_PATTERNS: list[tuple[re.Pattern[str], SectionFactType, float]] = [
    # ── REVOKE patterns ──────────────────────────────────────────
    (
        re.compile(r"призна(ть|л|ла|ло|ли)\s+(?:.*?\s+)?утратившим\s+силу", re.IGNORECASE),
        SectionFactType.REVOKE,
        0.95,
    ),
    (
        re.compile(r"призна(ть|л|ла|ло|ли)\s+(?:.*?\s+)?не\s+действующим", re.IGNORECASE),
        SectionFactType.REVOKE,
        0.90,
    ),
    (
        re.compile(r"отмен(ить|яет|яется|яются|ил|ила|ило|или)", re.IGNORECASE),
        SectionFactType.REVOKE,
        0.75,
    ),
    # ── MODIFY patterns ──────────────────────────────────────────
    (
        re.compile(r"внес(ти|ение|ения|ено|ены|ёт|ут)\s+(?:.*?\s+)?изменени", re.IGNORECASE),
        SectionFactType.MODIFY,
        0.85,
    ),
    (
        re.compile(r"изложить\s+(?:.*?\s+)?в\s+новой\s+редакции", re.IGNORECASE),
        SectionFactType.MODIFY,
        0.90,
    ),
    (
        re.compile(r"дополн(ить|ение|ения|ен|ена|ены|яет|яются)", re.IGNORECASE),
        SectionFactType.MODIFY,
        0.70,
    ),
    # ── ENACT patterns ───────────────────────────────────────────
    (
        re.compile(r"ввест(и|ить|ится|ятся|ил|ила|ило|или|ён|ена|ены)\s+(?:.*?\s+)?в\s+действие", re.IGNORECASE),
        SectionFactType.ENACT,
        0.90,
    ),
    (
        re.compile(r"вступа(ет|ют|яет|яют)\s+(?:.*?\s+)?в\s+силу", re.IGNORECASE),
        SectionFactType.ENACT,
        0.85,
    ),
    (
        re.compile(r"распространя(ется|ются|ет|ют)\s+(?:.*?\s+)?на", re.IGNORECASE),
        SectionFactType.RELATE,
        0.65,
    ),
]


class SectionAnalyzer:
    """Stub regex-based analyzer for document sections.

    Scans section text for predefined legal patterns and returns
    a list of detected SectionFact objects.

    This is a deliberate MVP stub. The regex approach has known
    limitations (false positives/negatives) and is intended to be
    replaced by LLM-based analysis in future iterations.
    """

    def __init__(self, patterns: list[tuple[re.Pattern[str], SectionFactType, float]] | None = None) -> None:
        """Initialize with optional custom patterns.

        Args:
            patterns: List of (compiled_regex, fact_type, confidence_weight) tuples.
                      Defaults to _PATTERNS if None.
        """
        self._patterns = patterns or _PATTERNS

    def analyze(self, _text: str, _section_external_id: str = "") -> list[SectionFact]:
        """Analyze section text and return detected legal facts.

        ⚠️ STUB: Always returns an empty list.
        Full implementation (regex → NER → LLM) is deferred — extracting
        the referenced document name/title from text is a non-trivial NLP
        task beyond the current PoC scope.

        When the real implementation is added, the persistence infrastructure
        (ChangeTrackingRepository.save_analysis_facts) is already complete
        and ready to receive SectionFact objects.

        Args:
            text: The text of the document section to analyze.
            section_external_id: Optional external ID of the section (for provenance).

        Returns:
            Empty list (stub).
        """
        # Stub: no-op until the full NLP-based implementation is ready.
        return []

    @staticmethod
    def _extract_target_id(text: str) -> str | None:
        """Try to extract a referenced document number from the matched text.

        Looks for patterns like "№ 123-ФЗ", "N 456", "№123".

        Returns:
            Document number string if found, None otherwise.
        """
        match = re.search(r"[№Nn]\s*(\d[\d\-\w]*)", text)
        return match.group(1) if match else None

    @staticmethod
    def _extract_date(text: str) -> date | None:
        """Try to extract a date from the matched text.

        Looks for Russian date patterns: "с 1 января 2024 года", "01.01.2024", etc.

        Returns:
            date if found, None otherwise.
        """
        # Try DD.MM.YYYY or DD/MM/YYYY
        match = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", text)
        if match:
            try:
                return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            except (ValueError, OverflowError):
                pass
        return None


__all__ = [
    "SectionAnalyzer",
    "SectionFact",
    "SectionFactType",
]
