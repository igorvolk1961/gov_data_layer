"""StubGetTocHandler — stub table-of-contents returning empty list."""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseGetTocHandler


class StubGetTocHandler(BaseGetTocHandler):
    """Return empty table of contents (stub mode)."""

    async def get_toc(self, document_id: str) -> list[dict[str, str]]:
        """Return an empty list (no TOC in stub mode).

        Args:
            document_id: Document identifier (unused).

        Returns:
            Empty list.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.get_toc",
            source_id=adapter.source_id,
            mode="stub",
            document_id=document_id,
        ) as span:
            span.set_input({"document_id": document_id})
            span.set_output([])
            return []


__all__ = [
    "StubGetTocHandler",
]
