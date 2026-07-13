"""ProductionListTopicsHandler — production list_topics via pravo.gov.ru API."""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseListTopicsHandler
from core.errors import SourceUnavailableError
from core.models.models import TopicNode
from core.observability.logger import get_logger

logger = get_logger(__name__)


class ProductionListTopicsHandler(BaseListTopicsHandler):
    """List rubricator topics using the real pravo.gov.ru API."""

    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """List rubricator topics in production mode.

        Args:
            parent_id: Parent topic ID. None = root topics.
            query: Optional search query.

        Returns:
            List of topic nodes.
        """
        adapter = self._adapter
        try:
            blocks = await adapter._pravo_client.get_public_blocks(parent=parent_id)
            topics = adapter._blocks_to_topics(blocks, parent_id or "")
            if query:
                topics = [t for t in topics if query.lower() in t.name.lower()]
            return topics
        except SourceUnavailableError:
            circuit_state = adapter._pravo_client.circuit_state
            logger.warning(
                "Failed to fetch topics from API (circuit: %s) — returning empty",
                circuit_state,
            )
            return []


__all__ = [
    "ProductionListTopicsHandler",
]
