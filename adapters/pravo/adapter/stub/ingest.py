"""StubIngestHandler — stub ingestion returning fixed document count."""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseIngestHandler
from adapters.pravo.adapter.stub._data import _build_stub_documents


class StubIngestHandler(BaseIngestHandler):
    """Ingest stub documents — returns count of fixed documents."""

    def __init__(self, adapter: object) -> None:
        """Initialize with stub documents."""
        super().__init__(adapter)
        self._stub_documents = _build_stub_documents()

    async def ingest(self) -> int:
        """Return the number of stub documents.

        Returns:
            Document count.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.ingest",
            source_id=adapter.source_id,
            mode="stub",
        ) as span:
            count = len(self._stub_documents)
            span.set_output({"count": count})
            return count


__all__ = [
    "StubIngestHandler",
]
