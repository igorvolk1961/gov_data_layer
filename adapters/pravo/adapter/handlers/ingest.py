"""BaseIngestHandler — abstract interface for ingest strategy."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseIngestHandler(ABC):
    """Abstract handler for the ingest() protocol method.

    Subclasses must implement ingest().
    """

    def __init__(self, adapter: object) -> None:
        """Initialize with a reference to the parent PravoAdapter.

        Args:
            adapter: The PravoAdapter instance.
        """
        self._adapter = adapter

    @abstractmethod
    async def ingest(self) -> int:
        """Ingest documents from the source.

        Returns:
            Number of ingested documents.
        """
        ...


__all__ = [
    "BaseIngestHandler",
]
