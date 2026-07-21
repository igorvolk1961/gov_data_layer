"""PassThroughReranker — identity reranker, returns chunks as-is.

Useful for:
- Testing / benchmarking: compare results with and without re-ranking
- Configurations where only raw vector similarity is desired
- As a base-line when evaluating other reranker strategies
"""

from __future__ import annotations

from typing import Any

from core.models.models import DocumentChunk
from core.reranker import Reranker


class PassThroughReranker(Reranker):
    """Identity reranker — preserves the original Qdrant ordering and scores.

    This reranker does not modify scores or ordering. It returns chunks
    exactly as they came from the vector store.
    """

    async def rerank(
        self,
        query: str,  # noqa: ARG002
        query_embedding: list[float],  # noqa: ARG002
        chunks: list[tuple[DocumentChunk, float]],
        topic_matches: list[dict[str, Any]] | None = None,  # noqa: ARG002
    ) -> list[tuple[DocumentChunk, float]]:
        """Return chunks unchanged (preserving Qdrant ordering).

        Args:
            query: Ignored — present for interface compatibility.
            query_embedding: Ignored — present for interface compatibility.
            chunks: Chunks to return as-is.
            topic_matches: Ignored — present for interface compatibility.

        Returns:
            The same list of ``(DocumentChunk, float)`` tuples, unchanged.
        """
        return chunks
