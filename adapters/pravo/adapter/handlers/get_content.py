"""BaseGetContentHandler — abstract interface for get_content strategy."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseGetContentHandler(ABC):
    """Abstract handler for the get_content() protocol method.

    Subclasses must implement get_content().
    """

    def __init__(self, adapter: object) -> None:
        """Initialize with a reference to the parent PravoAdapter.

        Args:
            adapter: The PravoAdapter instance.
        """
        self._adapter = adapter

    @abstractmethod
    async def get_content(self, document_id: str) -> str:
        """Get full document text.

        Args:
            document_id: Document identifier.

        Returns:
            Full document text content.

        Raises:
            NotFoundError: Document not found.
            SourceUnavailableError: Source unavailable or OCR not configured.
        """
        ...


__all__ = [
    "BaseGetContentHandler",
]
