"""TocMixin — mixin class that provides get_toc() for any SourceAdapter.

Uses the shared extract_toc_from_text() from toc_extractor.py to parse
document structure from OCR text. Mode-independent — works for any adapter
that implements get_content().
"""

from __future__ import annotations

from core.models.models import TocNode


class TocMixin:
    """Mixin that adds get_toc() to any SourceAdapter.

    The adapter must implement get_content(document_id) -> str.
    """

    async def get_toc(
        self,
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> list[TocNode]:
        """Extract document structure from text.

        Uses extract_toc_from_text() from toc_extractor.py.
        Mode-independent — same for stub and production.

        Args:
            document_id: Document identifier.
            parent_section_id: Optional parent section filter.
            query: Optional search query.

        Returns:
            List of TocNode objects.
        """
        from adapters.base.toc_extractor import extract_toc_from_text

        try:
            text = await self.get_content(document_id)  # type: ignore
        except Exception:
            return []

        return await extract_toc_from_text(text, document_id, parent_section_id, query)


__all__ = [
    "TocMixin",
]
