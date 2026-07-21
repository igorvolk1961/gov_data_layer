"""Reranker — pluggable chunk re-ranking after initial vector retrieval.

Usage::

    class MyReranker(Reranker):
        async def rerank(self, query, query_embedding, chunks, topic_matches=None):
            # custom logic
            return sorted(chunks, key=lambda x: x[1], reverse=True)
"""

from core.reranker._base import Reranker
from core.reranker.pass_through_reranker import PassThroughReranker
from core.reranker.topic_aware_reranker import TopicAwareReranker

__all__ = [
    "PassThroughReranker",
    "Reranker",
    "TopicAwareReranker",
]
