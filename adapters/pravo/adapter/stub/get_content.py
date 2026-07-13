"""StubGetContentHandler — stub content retrieval from cached documents."""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseGetContentHandler
from core.errors import NotFoundError


class StubGetContentHandler(BaseGetContentHandler):
    """Retrieve document content from adapter cache (populated by real HTTP calls)."""

    async def get_content(self, document_id: str) -> str:
        """Return the content of a document from the adapter cache.

        Args:
            document_id: Document identifier.

        Returns:
            Document content (summary text).

        Raises:
            NotFoundError: Document not found in cache.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.get_content",
            source_id=adapter.source_id,
            mode="stub",
            document_id=document_id,
        ) as span:
            span.set_input({"document_id": document_id})
            cached = adapter._document_cache.get(document_id)
            if cached is None:
                span.set_output({"error": "not_found"})
                raise NotFoundError(f"Document '{document_id}' not found in stub cache")
            doc, _ = cached
            content = doc.summary or ""
            span.set_output({"length": len(content)})
            return content


__all__ = [
    "StubGetContentHandler",
]
