"""Каноническая модель данных — единая схема нормализации для всех источников."""

from core.models.models import (
    Citation,
    ConfidenceSignals,
    DocumentChunk,
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
    "DocumentChunk",
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
