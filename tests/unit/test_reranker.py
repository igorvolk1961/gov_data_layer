"""Unit tests for the Reranker module.

Tests both ``TopicAwareReranker`` and ``PassThroughReranker``
implementations with mock chunks and topic matches.
"""

from __future__ import annotations

import pytest

from core.models.models import DocumentChunk
from core.reranker import PassThroughReranker, TopicAwareReranker

# ── Helpers ──────────────────────────────────────────────────────────


def _make_chunk(
    chunk_id: str,
    doc_id: str,
    text: str = "sample text",
    topic_ids: list[str] | None = None,
    topic_scores: dict[str, float] | None = None,
) -> DocumentChunk:
    """Create a DocumentChunk with minimal required fields."""
    return DocumentChunk(
        id=chunk_id,
        document_id=doc_id,
        doc_uuid="uuid-" + chunk_id,
        text=text,
        topic_ids=topic_ids or [],
        topic_scores=topic_scores or {},
    )


@pytest.fixture
def chunks_no_topics() -> list[tuple[DocumentChunk, float]]:
    """Three chunks with no topic associations — pure Qdrant score test."""
    return [
        (_make_chunk("c1", "doc-a"), 0.9),
        (_make_chunk("c2", "doc-b"), 0.7),
        (_make_chunk("c3", "doc-c"), 0.5),
    ]


@pytest.fixture
def chunks_with_topics() -> list[tuple[DocumentChunk, float]]:
    """Chunks where topic scores will affect the final ranking."""
    return [
        (
            _make_chunk(
                "c1",
                "doc-a",
                topic_ids=["t1", "t2"],
                topic_scores={"t1": 0.95, "t2": 0.3},
            ),
            0.6,
        ),
        (
            _make_chunk(
                "c2",
                "doc-b",
                topic_ids=["t2"],
                topic_scores={"t2": 0.85},
            ),
            0.8,
        ),
        (
            _make_chunk(
                "c3",
                "doc-c",
                topic_ids=["t3"],
                topic_scores={"t3": 0.5},
            ),
            0.4,
        ),
    ]


@pytest.fixture
def topic_matches() -> list[dict]:
    """Topic matches as returned by QdrantStore.search_topics()."""
    return [
        {"topic_id": "t1", "score": 0.9},
        {"topic_id": "t2", "score": 0.6},
    ]


# ── PassThroughReranker ──────────────────────────────────────────────


class TestPassThroughReranker:
    """Verify that PassThroughReranker returns chunks unchanged."""

    @pytest.mark.asyncio
    async def test_returns_chunks_unchanged(
        self, chunks_no_topics: list[tuple[DocumentChunk, float]]
    ) -> None:
        reranker = PassThroughReranker()
        result = await reranker.rerank(
            query="test query",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=chunks_no_topics,
        )
        assert result == chunks_no_topics
        # Verify ordering is preserved (by Qdrant score descending)
        scores = [s for _, s in result]
        assert scores == [0.9, 0.7, 0.5]

    @pytest.mark.asyncio
    async def test_ignores_topic_matches(
        self, chunks_no_topics: list[tuple[DocumentChunk, float]]
    ) -> None:
        reranker = PassThroughReranker()
        result = await reranker.rerank(
            query="test",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=chunks_no_topics,
            topic_matches=[{"topic_id": "t1", "score": 1.0}],
        )
        assert result == chunks_no_topics

    @pytest.mark.asyncio
    async def test_empty_chunks(self) -> None:
        reranker = PassThroughReranker()
        result = await reranker.rerank(
            query="test",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=[],
        )
        assert result == []


# ── TopicAwareReranker ───────────────────────────────────────────────


class TestTopicAwareReranker:
    """Verify TopicAwareReranker combines vector + topic scores correctly."""

    @pytest.mark.asyncio
    async def test_default_weights_preserve_order_no_topics(
        self, chunks_no_topics: list[tuple[DocumentChunk, float]]
    ) -> None:
        """Without topic matches, order should be preserved (S1 dominates)."""
        reranker = TopicAwareReranker()
        result = await reranker.rerank(
            query="test",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=chunks_no_topics,
        )
        scores = [s for _, s in result]
        # S1=0.9 → 0.6*0.9=0.54; S1=0.7 → 0.42; S1=0.5 → 0.3
        assert scores == pytest.approx([0.54, 0.42, 0.3])

    @pytest.mark.asyncio
    async def test_topic_boost_changes_ordering(
        self,
        chunks_with_topics: list[tuple[DocumentChunk, float]],
        topic_matches: list[dict],
    ) -> None:
        """Verify topic-aware scoring can re-order chunks.

        Expected scores with w_vector=0.6, w_topic=0.4:
        - c1 (doc-a): 0.6*0.6 + 0.4*sqrt(0.9*0.95) = 0.36 + 0.3699 = 0.7299
        - c2 (doc-b): 0.6*0.8 + 0.4*sqrt(0.6*0.85) = 0.48 + 0.2856 = 0.7656
        - c3 (doc-c): 0.6*0.4 + 0.4*sqrt(0) = 0.24
        """
        reranker = TopicAwareReranker()
        result = await reranker.rerank(
            query="test",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=chunks_with_topics,
            topic_matches=topic_matches,
        )

        doc_ids = [ch.document_id for ch, _ in result]
        # c2 first (S1=0.8 still strong), c1 second (boosted by topic), c3 last
        assert doc_ids == ["doc-b", "doc-a", "doc-c"], (
            f"Expected doc-b > doc-a > doc-c, got {doc_ids}"
        )

    @pytest.mark.asyncio
    async def test_custom_weights(
        self,
        chunks_with_topics: list[tuple[DocumentChunk, float]],
        topic_matches: list[dict],
    ) -> None:
        """With w_topic=0.8, topic boost should dominate, lifting c1 above c2."""
        reranker = TopicAwareReranker(w_vector=0.2, w_topic=0.8)
        result = await reranker.rerank(
            query="test",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=chunks_with_topics,
            topic_matches=topic_matches,
        )

        doc_ids = [ch.document_id for ch, _ in result]
        # c1 has strongest topic match (t1: S2=0.9 * S3=0.95)
        assert doc_ids[0] == "doc-a", f"Expected doc-a first with high topic weight, got {doc_ids}"

    @pytest.mark.asyncio
    async def test_no_topic_matches_falls_back_to_vector(
        self, chunks_with_topics: list[tuple[DocumentChunk, float]]
    ) -> None:
        """Without topic_matches, falls back to S1-only ordering."""
        reranker = TopicAwareReranker()
        result = await reranker.rerank(
            query="test",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=chunks_with_topics,
        )
        scores = [round(s, 4) for _, s in result]
        # 0.6*0.8=0.48, 0.6*0.6=0.36, 0.6*0.4=0.24
        assert scores == [0.48, 0.36, 0.24]

    @pytest.mark.asyncio
    async def test_empty_chunks(self) -> None:
        reranker = TopicAwareReranker()
        result = await reranker.rerank(
            query="test",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=[],
        )
        assert result == []

    def test_raises_on_negative_weights(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            TopicAwareReranker(w_vector=-0.1, w_topic=1.0)

    def test_raises_on_zero_sum_weights(self) -> None:
        with pytest.raises(ValueError, match="greater than zero"):
            TopicAwareReranker(w_vector=0.0, w_topic=0.0)

    def test_weight_properties(self) -> None:
        reranker = TopicAwareReranker(w_vector=0.7, w_topic=0.3)
        assert reranker.w_vector == 0.7
        assert reranker.w_topic == 0.3

    @pytest.mark.asyncio
    async def test_topic_score_never_exceeds_one(self) -> None:
        """Verify combined score is bounded [0.0, 1.0]."""
        chunk = _make_chunk(
            "c1",
            "doc-a",
            topic_ids=["t1"],
            topic_scores={"t1": 1.0},
        )
        chunks = [(chunk, 1.0)]
        matches = [{"topic_id": "t1", "score": 1.0}]

        reranker = TopicAwareReranker(w_vector=0.5, w_topic=0.5)
        result = await reranker.rerank(
            query="test",
            query_embedding=[0.1, 0.2, 0.3],
            chunks=chunks,
            topic_matches=matches,
        )
        # 0.5*1.0 + 0.5*sqrt(1.0*1.0) = 1.0
        score = result[0][1]
        assert score <= 1.0 + 1e-9
        assert score >= 0.0
