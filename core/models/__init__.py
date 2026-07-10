"""Каноническая модель данных — единая схема нормализации для всех источников."""

from core.models.models import (
    Citation,
    ConfidenceSignals,
    DocumentDetail,
    LegalStatus,
    OfficialDocument,
    SearchContext,
    SearchResponse,
    SearchResult,
    Source,
    SourceAvailability,
    TocNode,
    TopicNode,
)

__all__ = [
    "Citation",
    "ConfidenceSignals",
    "DocumentDetail",
    "LegalStatus",
    "OfficialDocument",
    "SearchContext",
    "SearchResponse",
    "SearchResult",
    "Source",
    "SourceAvailability",
    "TocNode",
    "TopicNode",
]
