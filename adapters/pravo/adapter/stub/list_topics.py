"""StubListTopicsHandler — stub topic listing from fixed data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from adapters.pravo.adapter.handlers import BaseListTopicsHandler
from adapters.pravo.adapter.stub._data import _build_stub_documents
from core.models.models import TopicNode

if TYPE_CHECKING:
    from adapters.pravo.adapter.base import PravoAdapterBase


class StubListTopicsHandler(BaseListTopicsHandler):
    """List topics derived from fixed stub documents."""

    def __init__(self, adapter: PravoAdapterBase) -> None:
        """Initialize with stub documents."""
        super().__init__(adapter)
        self._stub_documents = _build_stub_documents()

    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """Return unique topics from stub documents.

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
            for doc in self._stub_documents.values():
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
