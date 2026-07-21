"""TopicAwareReranker — combines vector similarity with topic relevance.

Formula::

    score = w_vector * S1 + w_topic * sqrt(max_over_topics(S2[t] * S3[t]))

Where:
    S1  = Qdrant raw vector similarity (cosine)
    S2  = query↔topic similarity (from ``search_topics()``)
    S3  = chunk↔topic similarity (from ``DocumentChunk.topic_scores``)

Weights ``w_vector`` and ``w_topic`` are configurable via constructor
and from ``config.yaml`` → ``reranker.weights``.
"""

from __future__ import annotations

import math
from typing import Any

from core.models.models import DocumentChunk
from core.reranker import Reranker


class TopicAwareReranker(Reranker):
    """Re-ranks chunks by combining vector similarity with topic relevance.

    Args:
        w_vector: Weight for Qdrant raw vector similarity (S1). Default 0.6.
        w_topic: Weight for topic relevance score (sqrt of S2*S3). Default 0.4.
    """

    def __init__(self, w_vector: float = 0.6, w_topic: float = 0.4) -> None:
        if w_vector < 0 or w_topic < 0:
            raise ValueError("Weights must be non-negative")
        if abs(w_vector + w_topic) < 1e-9:
            raise ValueError("Sum of weights must be greater than zero")
        self._w_vector = w_vector
        self._w_topic = w_topic

    @property
    def w_vector(self) -> float:
        """Weight for the Qdrant vector similarity score (S1)."""
        return self._w_vector

    @property
    def w_topic(self) -> float:
        """Weight for the topic relevance score (sqrt of S2*S3)."""
        return self._w_topic

    async def rerank(
        self,
        query: str,  # noqa: ARG002
        query_embedding: list[float],  # noqa: ARG002
        chunks: list[tuple[DocumentChunk, float]],
        topic_matches: list[dict[str, Any]] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """Re-rank chunks using combined vector + topic scoring.
            chunks: List of ``(DocumentChunk, S1)`` tuples from Qdrant.
            topic_matches: Optional list of ``[{"topic_id": str, "score": float}]``
                          from ``search_topics()`` — provides S2 scores.

        Returns:
            Chunks sorted by combined score in descending order.
        """
        # Build S2 lookup: topic_id → query↔topic similarity
        topic_id_to_s2: dict[str, float] = {}
        if topic_matches:
            for m in topic_matches:
                tid = m.get("topic_id", "")
                score = m.get("score", 0.0)
                if tid:
                    topic_id_to_s2[tid] = float(score)

        ranked: list[tuple[DocumentChunk, float]] = []
        for chunk, s1 in chunks:
            # S3: chunk↔topic similarity from payload
            # S2: query↔topic similarity from search_topics()
            max_topic_score = 0.0
            for tid in chunk.topic_ids:
                s2 = topic_id_to_s2.get(tid, 0.0)
                s3 = chunk.topic_scores.get(tid, 0.0)
                max_topic_score = max(max_topic_score, s2 * s3)

            combined = self._w_vector * s1 + self._w_topic * math.sqrt(max_topic_score)
            ranked.append((chunk, combined))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked
