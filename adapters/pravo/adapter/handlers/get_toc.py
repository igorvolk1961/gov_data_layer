"""BaseGetTocHandler — abstract base for table-of-contents retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.models.models import TocNode

if TYPE_CHECKING:
    from adapters.pravo.adapter.base import PravoAdapterBase


class BaseGetTocHandler(ABC):
    """Abstract handler for get_toc protocol method."""

    def __init__(self, adapter: PravoAdapterBase) -> None:
        """Initialize with a reference to the parent adapter.

        Args:
            adapter: The PravoAdapter instance.
        """
        self._adapter = adapter

    @abstractmethod
    async def get_toc(
        self,
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> list[TocNode]:
        """Get document table of contents.

        Args:
            document_id: Document identifier.
            parent_section_id: Optional parent section filter.
            query: Optional search query.

        Returns:
            List of table-of-contents nodes.
        """
        ...


__all__ = [
    "BaseGetTocHandler",
]
