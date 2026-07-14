"""Unit tests for DocStructSplitter.

Verifies that split_text() returns both chunks and TOC from a single parse.
split_text() is async — all tests use pytest-asyncio.
"""

from __future__ import annotations

import pytest

from core.ingest.chunker import DocStructSplitter
from core.models.models import DocumentChunk, TocNode


@pytest.fixture
def splitter() -> DocStructSplitter:
    return DocStructSplitter(max_chunk_size=1000, chunk_overlap=200)


SAMPLE_TEXT = """Раздел I. Общие положения
Статья 1. Основные понятия
Для целей настоящего закона используются следующие основные понятия.
Статья 2. Сфера применения
Настоящий закон распространяется на все отношения.
Раздел II. Заключительные положения
Статья 3. Вступление в силу
Настоящий закон вступает в силу со дня опубликования."""


class TestDocStructSplitter:
    """Test that split_text returns both chunks and TOC from one parse."""

    @pytest.mark.asyncio
    async def test_split_text_returns_tuple(self, splitter: DocStructSplitter) -> None:
        """split_text should return (list[DocumentChunk], list[TocNode])."""
        result = await splitter.split_text(SAMPLE_TEXT, "doc-1", "uuid-1")
        assert isinstance(result, tuple)
        assert len(result) == 2
        chunks, toc = result
        assert isinstance(chunks, list)
        assert isinstance(toc, list)

    @pytest.mark.asyncio
    async def test_split_text_returns_document_chunks(self, splitter: DocStructSplitter) -> None:
        """Chunks should be DocumentChunk instances with correct fields."""
        chunks, _toc = await splitter.split_text(SAMPLE_TEXT, "doc-1", "uuid-1")
        assert len(chunks) > 0, "Should produce at least one chunk"
        for chunk in chunks:
            assert isinstance(chunk, DocumentChunk)
            assert chunk.id, "Chunk should have an id"
            assert chunk.document_id == "doc-1"
            assert chunk.doc_uuid == "uuid-1"
            assert chunk.text, "Chunk should have text"
            assert chunk.chunk_index >= 0

    @pytest.mark.asyncio
    async def test_split_text_returns_toc(self, splitter: DocStructSplitter) -> None:
        """TOC should contain TocNode instances with correct structure."""
        _chunks, toc = await splitter.split_text(SAMPLE_TEXT, "doc-1", "uuid-1")
        assert len(toc) > 0, "Should produce at least one TOC entry"
        for node in toc:
            assert isinstance(node, TocNode)
            assert node.id, "TOC node should have an id"
            assert node.document_id == "doc-1"
            assert node.title, "TOC node should have a title"
            assert node.level >= 0

    @pytest.mark.asyncio
    async def test_toc_hierarchy(self, splitter: DocStructSplitter) -> None:
        """TOC should have proper parent-child relationships."""
        _chunks, toc = await splitter.split_text(SAMPLE_TEXT, "doc-1", "uuid-1")
        # Find root nodes
        roots = [n for n in toc if n.parent_id == ""]
        assert len(roots) > 0, "Should have at least one root TOC node"
        # Verify child counts are computed
        for node in toc:
            children = [n for n in toc if n.parent_id == node.id]
            assert node.child_count == len(children)

    @pytest.mark.asyncio
    async def test_chunks_have_section_path(self, splitter: DocStructSplitter) -> None:
        """Chunks should have section_path populated."""
        chunks, _toc = await splitter.split_text(SAMPLE_TEXT, "doc-1", "uuid-1")
        for chunk in chunks:
            assert isinstance(chunk.section_path, list)

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self, splitter: DocStructSplitter) -> None:
        """Empty text should return empty lists."""
        chunks, toc = await splitter.split_text("", "doc-1", "uuid-1")
        assert chunks == []
        assert toc == []

    @pytest.mark.asyncio
    async def test_same_document_id_in_chunks_and_toc(self, splitter: DocStructSplitter) -> None:
        """Both chunks and TOC should use the same document_id."""
        chunks, toc = await splitter.split_text(SAMPLE_TEXT, "pravo-123", "uuid-1")
        for chunk in chunks:
            assert chunk.document_id == "pravo-123"
        for node in toc:
            assert node.document_id == "pravo-123"

    @pytest.mark.asyncio
    async def test_multiple_calls_consistent(self, splitter: DocStructSplitter) -> None:
        """Calling split_text twice on same text should produce same structure."""
        chunks1, toc1 = await splitter.split_text(SAMPLE_TEXT, "doc-1", "uuid-1")
        chunks2, toc2 = await splitter.split_text(SAMPLE_TEXT, "doc-1", "uuid-1")
        assert len(chunks1) == len(chunks2)
        assert len(toc1) == len(toc2)
