"""BaseListTopicsHandler — abstract interface for list_topics strategy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.models.models import TopicNode

if TYPE_CHECKING:
    from adapters.pravo.adapter.base import PravoAdapterBase


class BaseListTopicsHandler(ABC):
    """Abstract handler for the list_topics() protocol method.

    Subclasses must implement list_topics().
    """

    def __init__(self, adapter: PravoAdapterBase) -> None:
        """Initialize with a reference to the parent PravoAdapter.

        Args:
            adapter: The PravoAdapter instance.
        """
        self._adapter = adapter

    @abstractmethod
    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """List rubricator topics.

        Args:
            parent_id: Parent topic ID. None = root topics.
            query: Optional search query to filter topics by name.

        Returns:
            List of topic nodes.
        """
        ...


__all__ = [
    "BaseListTopicsHandler",
]
