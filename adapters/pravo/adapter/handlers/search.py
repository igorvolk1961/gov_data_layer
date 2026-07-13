"""BaseSearchHandler — abstract interface for search strategy."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models.models import SearchContext, SearchResult


class BaseSearchHandler(ABC):
    """Abstract handler for the search() protocol method.

    Subclasses must implement search().
    """

    def __init__(self, adapter: object) -> None:
        """Initialize with a reference to the parent PravoAdapter.

        Args:
            adapter: The PravoAdapter instance (provides access to
                _pravo_client, _parser, tracer, etc.).
        """
        self._adapter = adapter

    @abstractmethod
    async def search(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> list[SearchResult]:
        """Search documents.

        Args:
            query: Search query string.
            context: Optional filtering context.

        Returns:
            List of matching search results.
        """
        ...


__all__ = [
    "BaseSearchHandler",
]
