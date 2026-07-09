"""Каноническая модель данных — единая схема нормализации для всех источников."""

from core.models.models import (
    Citation,
    ConfidenceSignals,
    LegalStatus,
    OfficialDocument,
    SearchContext,
    SearchResult,
    Source,
    SourceAvailability,
    TocNode,
    TopicNode,
)

__all__ = [
    "Citation",
    "ConfidenceSignals",
    "LegalStatus",
    "OfficialDocument",
    "SearchContext",
    "SearchResult",
    "Source",
    "SourceAvailability",
    "TocNode",
    "TopicNode",
]
