"""Unit tests for SectionAnalyzer — regex-based legal fact detection."""

from __future__ import annotations

import pytest

from core.analyzer.section_analyzer import SectionAnalyzer, SectionFact, SectionFactType


@pytest.fixture
def analyzer() -> SectionAnalyzer:
    return SectionAnalyzer()


class TestSectionAnalyzer:
    """Test regex pattern matching for legal fact types."""

    # ── REVOKE tests ──────────────────────────────────────────────

    @pytest.mark.parametrize(
        "text",
        [
            "Признать утратившим силу постановление Правительства РФ",
            "признать утратившим силу",
            "Признал утратившим силу приказ № 123",
            "Признали утратившим силу распоряжение",
        ],
    )
    def test_detects_revoke_patterns(self, analyzer: SectionAnalyzer, text: str) -> None:
        """Text with 'признать утратившим силу' should be detected as REVOKE."""
        facts = analyzer.analyze(text, section_external_id="1")
        assert any(f.fact_type == SectionFactType.REVOKE for f in facts), (
            f"Expected REVOKE for: {text}"
        )
        for f in facts:
            if f.fact_type == SectionFactType.REVOKE:
                assert f.confidence >= 0.9
                assert f.section_external_id == "1"

    def test_detects_revoke_otmenit(self, analyzer: SectionAnalyzer) -> None:
        """'Отменить' should be detected as REVOKE."""
        facts = analyzer.analyze("Отменить приказ Министерства юстиции")
        assert any(f.fact_type == SectionFactType.REVOKE for f in facts)

    def test_detects_revoke_ne_deystvuyushim(self, analyzer: SectionAnalyzer) -> None:
        """'Признать не действующим' should be detected as REVOKE."""
        facts = analyzer.analyze("Признать не действующим пункт 2")
        assert any(f.fact_type == SectionFactType.REVOKE for f in facts)

    # ── MODIFY tests ──────────────────────────────────────────────

    @pytest.mark.parametrize(
        "text",
        [
            "Внести изменения в Федеральный закон",
            "Внесение изменений в постановление № 456",
            "Внести следующие изменения",
        ],
    )
    def test_detects_modify_patterns(self, analyzer: SectionAnalyzer, text: str) -> None:
        """Text with 'внести изменения' should be detected as MODIFY."""
        facts = analyzer.analyze(text)
        assert any(f.fact_type == SectionFactType.MODIFY for f in facts), (
            f"Expected MODIFY for: {text}"
        )

    def test_detects_modify_new_edition(self, analyzer: SectionAnalyzer) -> None:
        """'Изложить в новой редакции' should be detected as MODIFY."""
        facts = analyzer.analyze("Изложить статью 3 в новой редакции")
        assert any(f.fact_type == SectionFactType.MODIFY for f in facts)

    def test_detects_modify_dopolnit(self, analyzer: SectionAnalyzer) -> None:
        """'Дополнить' should be detected as MODIFY."""
        facts = analyzer.analyze("Дополнить пунктом 3.1")
        assert any(f.fact_type == SectionFactType.MODIFY for f in facts)

    # ── ENACT tests ───────────────────────────────────────────────

    @pytest.mark.parametrize(
        "text",
        [
            "Ввести в действие настоящее постановление",
            "Вводится в действие с 1 января",
        ],
    )
    def test_detects_enact_patterns(self, analyzer: SectionAnalyzer, text: str) -> None:
        """Text with 'ввести в действие' should be detected as ENACT."""
        facts = analyzer.analyze(text)
        assert any(f.fact_type == SectionFactType.ENACT for f in facts), (
            f"Expected ENACT for: {text}"
        )

    def test_detects_enact_vstupaet_v_silu(self, analyzer: SectionAnalyzer) -> None:
        """'Вступает в силу' should be detected as ENACT."""
        facts = analyzer.analyze("Настоящий закон вступает в силу с 01.01.2024")
        assert any(f.fact_type == SectionFactType.ENACT for f in facts)

    # ── RELATE tests ──────────────────────────────────────────────

    def test_detects_relate_pattern(self, analyzer: SectionAnalyzer) -> None:
        """'Распространяется на' should be detected as RELATE."""
        facts = analyzer.analyze("Действие настоящего закона распространяется на всех граждан")
        assert any(f.fact_type == SectionFactType.RELATE for f in facts)

    # ── Edge cases ────────────────────────────────────────────────

    def test_empty_text_returns_empty(self, analyzer: SectionAnalyzer) -> None:
        """Empty text should return no facts."""
        facts = analyzer.analyze("")
        assert facts == []

    def test_no_match_returns_empty(self, analyzer: SectionAnalyzer) -> None:
        """Text with no patterns should return no facts."""
        facts = analyzer.analyze("Обычный текст без специальных паттернов")
        assert facts == []

    def test_multiple_facts_in_one_text(self, analyzer: SectionAnalyzer) -> None:
        """Text with multiple patterns should detect all of them."""
        facts = analyzer.analyze(
            "Признать утратившим силу постановление № 123. "
            "Внести изменения в статью 5. "
            "Ввести в действие с 01.01.2024."
        )
        types = {f.fact_type for f in facts}
        assert SectionFactType.REVOKE in types
        assert SectionFactType.MODIFY in types
        assert SectionFactType.ENACT in types

    def test_dedup_same_pattern(self, analyzer: SectionAnalyzer) -> None:
        """Repeated identical matches should be deduplicated."""
        facts = analyzer.analyze(
            "Признать утратившим силу. Признать утратившим силу."
        )
        revoke_facts = [f for f in facts if f.fact_type == SectionFactType.REVOKE]
        assert len(revoke_facts) == 1, f"Expected 1 REVOKE fact, got {len(revoke_facts)}"

    # ── Target extraction tests ───────────────────────────────────

    def test_extracts_document_number(self, analyzer: SectionAnalyzer) -> None:
        """Should extract referenced document number."""
        facts = analyzer.analyze("Признать утратившим силу постановление № 123-ФЗ")
        revoke = [f for f in facts if f.fact_type == SectionFactType.REVOKE]
        assert revoke
        assert revoke[0].target_document_id == "123-ФЗ"

    # ── SectionFact tests ─────────────────────────────────────────

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
