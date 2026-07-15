"""Unit tests for SectionAnalyzer — stub that returns empty lists.

The analyzer is deliberately a no-op stub. The persistence infrastructure
(ChangeTrackingRepository.save_analysis_facts) is complete and tested
separately. Full NLP-based analysis is deferred.
"""

from __future__ import annotations

import pytest

from core.analyzer.section_analyzer import SectionAnalyzer, SectionFact, SectionFactType


@pytest.fixture
def analyzer() -> SectionAnalyzer:
    return SectionAnalyzer()


class TestSectionAnalyzerStub:
    """SectionAnalyzer is a stub — always returns empty list."""

    def test_analyze_returns_empty(self, analyzer: SectionAnalyzer) -> None:
        """Analyzer should return empty list (stub)."""
        facts = analyzer.analyze("Признать утратившим силу постановление № 123")
        assert facts == []

    def test_analyze_empty_text(self, analyzer: SectionAnalyzer) -> None:
        """Empty text should also return empty list."""
        facts = analyzer.analyze("")
        assert facts == []

    def test_analyze_any_text(self, analyzer: SectionAnalyzer) -> None:
        """Any text returns empty list (stub)."""
        facts = analyzer.analyze("Обычный текст")
        assert facts == []


class TestSectionFactModel:
    """SectionFact model is ready for when analysis is implemented."""

    def test_section_fact_creation(self) -> None:
        fact = SectionFact(
            fact_type=SectionFactType.REVOKE,
            section_external_id="1",
            text="признать утратившим силу",
            confidence=0.95,
            target_document_id="123-ФЗ",
        )
        assert fact.fact_type == SectionFactType.REVOKE
        assert fact.section_external_id == "1"
        assert fact.confidence == 0.95
        assert fact.target_document_id == "123-ФЗ"

    def test_section_fact_repr(self) -> None:
        fact = SectionFact(
            fact_type=SectionFactType.REVOKE,
            section_external_id="1",
            text="признать утратившим силу",
            confidence=0.95,
        )
        assert "REVOKE" in repr(fact)
        assert "section=1" in repr(fact)

    def test_section_fact_to_dict(self) -> None:
        fact = SectionFact(
            fact_type=SectionFactType.REVOKE,
            section_external_id="1",
            text="признать утратившим силу",
            confidence=0.95,
            target_document_id="123-ФЗ",
        )
        d = fact.to_dict()
        assert d["fact_type"] == "revoke"
        assert d["target_document_id"] == "123-ФЗ"
        assert d["confidence"] == 0.95

    def test_section_fact_types(self) -> None:
        assert SectionFactType.REVOKE.value == "revoke"
        assert SectionFactType.MODIFY.value == "modify"
        assert SectionFactType.ENACT.value == "enact"
        assert SectionFactType.RELATE.value == "relate"
        assert SectionFactType.UNKNOWN.value == "unknown"
