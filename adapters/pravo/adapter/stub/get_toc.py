"""StubGetTocHandler — stub table-of-contents returning empty list."""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseGetTocHandler
from core.models.models import TocNode


class StubGetTocHandler(BaseGetTocHandler):
    """Return empty table of contents (stub mode)."""

    async def get_toc(
        self,
        document_id: str,
        _parent_section_id: str | None = None,
        _query: str = "",
    ) -> list[TocNode]:
        """Return an empty list (no TOC in stub mode).

        Args:
            document_id: Document identifier (unused).
            _parent_section_id: Optional parent section filter (unused).
            _query: Optional search query (unused).

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
            span.set_output({"toc": []})
            return []


__all__ = [
    "StubGetTocHandler",
]
