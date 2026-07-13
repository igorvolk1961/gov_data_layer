"""BaseGetHandler — abstract interface for get strategy."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models.models import OfficialDocument


class BaseGetHandler(ABC):
    """Abstract handler for the get() protocol method.

    Subclasses must implement get().
    """

    def __init__(self, adapter: object) -> None:
        """Initialize with a reference to the parent PravoAdapter.

        Args:
            adapter: The PravoAdapter instance.
        """
        self._adapter = adapter

    @abstractmethod
    async def get(self, document_id: str) -> OfficialDocument:
        """Get a document by its identifier.

        Args:
            document_id: Document identifier.

        Returns:
            The full document model.

        Raises:
            NotFoundError: Document not found.
            SourceUnavailableError: Source unavailable.
        """
        ...


__all__ = [
    "BaseGetHandler",
]
