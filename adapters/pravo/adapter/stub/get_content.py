"""StubGetContentHandler — stub content retrieval from fixed data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from adapters.pravo.adapter.handlers import BaseGetContentHandler
from adapters.pravo.adapter.stub._data import _build_stub_documents
from core.errors import NotFoundError

if TYPE_CHECKING:
    from adapters.pravo.adapter.base import PravoAdapterBase


class StubGetContentHandler(BaseGetContentHandler):
    """Retrieve document content from fixed stub data."""

    def __init__(self, adapter: PravoAdapterBase) -> None:
        """Initialize with stub documents."""
        super().__init__(adapter)
        self._stub_documents = _build_stub_documents()

    async def get_content(self, document_id: str) -> str:
        """Return the content of a stub document.

        Args:
            document_id: Document identifier.

        Returns:
            Document content (summary text).

        Raises:
            NotFoundError: Document not found.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.get_content",
            source_id=adapter.source_id,
            mode="stub",
            document_id=document_id,
        ) as span:
            span.set_input({"document_id": document_id})
            doc = self._stub_documents.get(document_id)
            if doc is None:
                span.set_output({"error": "not_found"})
                raise NotFoundError(f"Document '{document_id}' not found in stub data")
            content = doc.summary or ""
            span.set_output({"length": len(content)})
            return content


__all__ = [
    "StubGetContentHandler",
]
