"""StubListTopicsHandler — stub topic listing from cached documents."""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseListTopicsHandler
from core.models.models import TopicNode


class StubListTopicsHandler(BaseListTopicsHandler):
    """List topics derived from cached documents (populated by real HTTP calls)."""

    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """Return unique topics from cached documents.

        Args:
            parent_id: Optional parent topic filter (unused in stub).
            query: Optional search query filter.

        Returns:
            List of topic nodes.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.list_topics",
            source_id=adapter.source_id,
            mode="stub",
        ) as span:
            span.set_input({"parent_id": parent_id, "query": query})
            seen: set[str] = set()
            topics: list[TopicNode] = []
            for doc, _ in adapter._document_cache.values():
                for t in doc.topic:
                    if t not in seen:
                        seen.add(t)
                        topics.append(
                            TopicNode(
                                id=t,
                                name=t,
                                parent_id="",
                                description="",
                                child_count=0,
                                document_count=0,
                            )
                        )
            span.set_output({"count": len(topics)})
            return topics


__all__ = [
    "StubListTopicsHandler",
]
