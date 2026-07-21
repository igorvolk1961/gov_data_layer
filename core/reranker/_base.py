"""Reranker — abstract base class for pluggable chunk re-ranking."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.models.models import DocumentChunk


class Reranker(ABC):
    """Abstract reranker — re-orders chunks after initial retrieval.

    Subclasses must implement ``rerank()``. The method receives:

    Args:
        query: The original search query text.
        query_embedding: The embedding vector of the query.
        chunks: List of ``(DocumentChunk, float)`` tuples as returned
                by the vector store, sorted by the store's native score
                (e.g. cosine similarity) in descending order.
        topic_matches: Optional list of dicts ``[{"topic_id": str, "score": float}]``
                       from ``QdrantStore.search_topics()``, representing
                       semantic similarity between the query and known topics.

    Returns:
        The same list of ``(DocumentChunk, float)`` tuples, but re-sorted
        by the reranker's composite score in **descending** order.
        The float score should be in [0.0, 1.0] range.
    """

    @abstractmethod
    async def rerank(
        self,
        query: str,
        query_embedding: list[float],
        chunks: list[tuple[DocumentChunk, float]],
        topic_matches: list[dict[str, Any]] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """Re-rank chunks and return them sorted by new score (descending)."""
        ...
