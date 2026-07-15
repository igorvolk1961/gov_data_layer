"""Analyzer — semantic analysis of document sections.

Currently provides a regex-based stub SectionAnalyzer for MVP.
Full semantic analysis (LLM-based) is planned for future iterations.
"""

from core.analyzer.section_analyzer import SectionAnalyzer, SectionFact, SectionFactType

__all__ = [
    "SectionAnalyzer",
    "SectionFact",
    "SectionFactType",
]
