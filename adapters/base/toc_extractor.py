"""TOC Extractor — shared utility for extracting document structure from text.

Uses DocStructSplitter which does ONE parse and returns both chunks and TOC.
This function takes only the TOC part.
"""

from __future__ import annotations

from core.ingest.chunker import DocStructSplitter
from core.models.models import DocumentChunk, TocNode


async def extract_toc_from_text(
    text: str,
    document_id: str,
    parent_section_id: str | None = None,
    query: str = "",
) -> list[TocNode]:
    """Extract table of contents from document text.

    Uses DocStructSplitter.split_text() which parses the text ONCE and
    returns both chunks and TOC. We take only the TOC part.

    Args:
        text: Full document text (from OCR).
        document_id: Document identifier.
        parent_section_id: Optional filter by parent section.
        query: Optional filter by section title.

    Returns:
        List of TocNode objects.
    """
    if not text:
        return []

    splitter = DocStructSplitter()
    _, toc = await splitter.split_text(text, document_id, doc_uuid="")

    if parent_section_id is not None:
        toc = [n for n in toc if n.parent_id == parent_section_id]

    if query:
        toc = [n for n in toc if query.lower() in n.title.lower()]

    for node in toc:
        node.child_count = sum(1 for n in toc if n.parent_id == node.id)

    return toc


def chunks_to_toc(
    chunks: list[DocumentChunk],
    document_id: str,
) -> list[TocNode]:
    """Derive TOC from existing chunks without re-parsing.

    Args:
        chunks: Already-parsed DocumentChunk objects.
        document_id: Document identifier.

    Returns:
        List of TocNode objects.
    """

    seen_paths: set[str] = set()
    toc: list[TocNode] = []

    for chunk in chunks:
        if not chunk.section_path:
            continue
        for level, section_title in enumerate(chunk.section_path):
            path_key = "|".join(chunk.section_path[: level + 1])
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            parent_path = "|".join(chunk.section_path[:level]) if level > 0 else ""
            toc.append(
                TocNode(
                    id=path_key,
                    document_id=document_id,
                    title=section_title,
                    parent_id=parent_path,
                    level=level,
                    child_count=0,
                )
            )

    for node in toc:
        node.child_count = sum(1 for n in toc if n.parent_id == node.id)

    return toc


__all__ = [
    "chunks_to_toc",
    "extract_toc_from_text",
]
