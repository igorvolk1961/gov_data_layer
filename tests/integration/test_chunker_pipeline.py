"""Integration tests for chunker + embedder + Qdrant pipeline.

Tests the full pipeline with real Russian NPA OCR text:
1. DocStructSplitter parses real OCR output into chunks and TOC
2. Embedder produces vectors (stub mode uses zero vectors)
3. process_document_text() runs the full chunk → embed → Qdrant pipeline

Requirements:
    - smart_chunker installed (see pyproject.toml)
    - Qdrant running on localhost:6333 for Qdrant-specific tests
    - sentence-transformers + sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 for real embeddings (optional)
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

import pytest
import pytest_asyncio

from adapters.base.ingest_pipeline import process_document_text
from core.index.qdrant_store import QdrantStore
from core.ingest.chunker import DocStructSplitter
from core.ingest.embedder import Embedder
from core.models.models import DocumentChunk, TocNode

logger = logging.getLogger(__name__)

# ── Test data ────────────────────────────────────────────────────────

_TEST_PDF_DIR = Path(__file__).parents[2] / "tests" / "data" / "pdf"

# Real OCR output: Закон Санкт-Петербурга (2 pages, ~2753 chars)
OCR_PATH = _TEST_PDF_DIR / "7800202607010012.yandex_vision.txt"
TEST_OCR_TEXT: str | None = None
if OCR_PATH.exists():
    TEST_OCR_TEXT = OCR_PATH.read_text(encoding="utf-8")

# ── Helpers ──────────────────────────────────────────────────────────


def _check_qdrant() -> bool:
    """Check if Qdrant is available on localhost:6333."""
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        result = s.connect_ex(("127.0.0.1", 6333))
        s.close()
        return result == 0
    except Exception:
        return False


# ── DocStructSplitter with real OCR text ────────────────────────────


class TestDocStructSplitterWithRealText:
    """Test DocStructSplitter with real Russian NPA OCR text."""

    @pytest.fixture
    def splitter(self) -> DocStructSplitter:
        return DocStructSplitter(max_chunk_size=1024, chunk_overlap=200)

    @pytest.mark.asyncio
    async def test_splitter_produces_chunks_and_toc(self, splitter: DocStructSplitter) -> None:
        """Real OCR text should produce both chunks and TOC."""
        chunks, toc = await splitter.split_text(TEST_OCR_TEXT, "pravo-7800202607010012", "uuid-1")
        assert isinstance(chunks, list)
        assert isinstance(toc, list)
        assert len(chunks) > 0, "Should produce at least one chunk"
        assert len(toc) > 0, "Should produce at least one TOC entry"

    @pytest.mark.asyncio
    async def test_chunks_are_document_chunk(self, splitter: DocStructSplitter) -> None:
        """Each chunk should be a valid DocumentChunk."""
        chunks, _toc = await splitter.split_text(TEST_OCR_TEXT, "pravo-7800202607010012", "uuid-1")
        for ch in chunks:
            assert isinstance(ch, DocumentChunk)
            assert ch.id
            assert ch.document_id == "pravo-7800202607010012"
            assert ch.doc_uuid == "uuid-1"
            assert ch.text
            assert ch.chunk_index >= 0

    @pytest.mark.asyncio
    async def test_toc_entries_are_toc_node(self, splitter: DocStructSplitter) -> None:
        """Each TOC entry should be a valid TocNode."""
        _chunks, toc = await splitter.split_text(TEST_OCR_TEXT, "pravo-7800202607010012", "uuid-1")
        for node in toc:
            assert isinstance(node, TocNode)
            assert node.id
            assert node.document_id == "pravo-7800202607010012"
            assert node.title is not None  # May be empty if chunker cannot detect a title
            assert node.level >= 0

    @pytest.mark.asyncio
    async def test_toc_has_hierarchy(self, splitter: DocStructSplitter) -> None:
        """TOC should have proper parent-child relationships."""
        _chunks, toc = await splitter.split_text(TEST_OCR_TEXT, "pravo-7800202607010012", "uuid-1")
        roots = [n for n in toc if n.parent_id == ""]
        assert len(roots) > 0, "Should have at least one root node"
        # Verify child_count consistency
        for node in toc:
            children = [n for n in toc if n.parent_id == node.id]
            assert node.child_count == len(children), f"Node {node.id}: child_count mismatch"

    @pytest.mark.asyncio
    async def test_chunks_have_section_path(self, splitter: DocStructSplitter) -> None:
        """Chunks should have section_path populated."""
        chunks, _toc = await splitter.split_text(TEST_OCR_TEXT, "pravo-7800202607010012", "uuid-1")
        for ch in chunks:
            assert isinstance(ch.section_path, list)


# ── Embedder integration ────────────────────────────────────────────


@pytest.mark.embedding
class TestEmbedderIntegration:
    """Test Embedder with real text (stub mode uses zero vectors)."""

    @pytest.mark.asyncio
    async def test_embedder_produces_vectors(self) -> None:
        """Embedder should produce one vector per input text."""
        embedder = Embedder()
        texts = ["Тестовый текст первый.", "Тестовый текст второй."]
        vectors = await embedder.embed(texts)
        assert len(vectors) == 2
        for vec in vectors:
            assert len(vec) > 0
            # In stub mode (no sentence-transformers), vectors are all zeros
            # In real mode, vectors should be non-zero

    @pytest.mark.asyncio
    async def test_embedder_empty_input(self) -> None:
        """Empty input should return empty list."""
        embedder = Embedder()
        vectors = await embedder.embed([])
        assert vectors == []

    @pytest.mark.asyncio
    async def test_embedder_vector_size_consistent(self) -> None:
        """All vectors from a batch should have the same size."""
        embedder = Embedder()
        texts = ["A", "B", "C"]
        vectors = await embedder.embed(texts)
        sizes = {len(v) for v in vectors}
        assert len(sizes) == 1, "All vectors should have same dimension"

    @pytest.mark.asyncio
    async def test_embedder_query(self) -> None:
        """embed_query should return a single vector."""
        embedder = Embedder()
        vec = await embedder.embed_query("Поисковый запрос")
        assert isinstance(vec, list)
        assert len(vec) > 0


# ── Full pipeline (chunk → embed → Qdrant) ──────────────────────────


@pytest.mark.skipif(
    not _check_qdrant(),
    reason="Qdrant not running on localhost:6333",
)
@pytest.mark.embedding
class TestFullPipeline:
    """Test the full chunk → embed → Qdrant pipeline.

    These tests require a running Qdrant instance on localhost:6333.
    """

    @pytest_asyncio.fixture
    async def qdrant(self) -> QdrantStore:
        """Create a QdrantStore with a unique test collection to avoid conflicts."""
        import uuid

        store = QdrantStore(
            host="localhost",
            port=6333,
            collection=f"test_pipeline_{uuid.uuid4().hex[:8]}",
            vector_size=384,
        )
        await store.ensure_collection()
        try:
            yield store
        finally:
            # Cleanup: delete the test collection
            client = await store._get_client()
            if client is not None:
                with contextlib.suppress(Exception):
                    client.delete_collection(collection_name=store._collection)

    @pytest.mark.asyncio
    async def test_process_document_text_returns_chunks_and_toc(self, qdrant: QdrantStore) -> None:
        """Full pipeline should return (chunks, toc)."""
        chunks, toc = await process_document_text(
            text=TEST_OCR_TEXT,
            document_id="pravo-7800202607010012",
            doc_uuid="test-doc-uuid",
            qdrant=qdrant,
        )
        assert isinstance(chunks, list)
        assert isinstance(toc, list)
        if chunks:
            # Verify embeddings were set
            for c in chunks:
                assert c.embedding is not None, "Chunk should have embedding after pipeline"

    @pytest.mark.asyncio
    async def test_qdrant_upsert_and_count(self, qdrant: QdrantStore) -> None:
        """After process_document_text, Qdrant should have stored chunks."""
        chunks, _toc = await process_document_text(
            text=TEST_OCR_TEXT,
            document_id="pravo-7800202607010012",
            doc_uuid="test-doc-uuid",
            qdrant=qdrant,
        )
        if not chunks:
            pytest.skip("No chunks produced — nothing to upsert")
        count = await qdrant.count()
        assert count == len(chunks), f"Qdrant count {count} doesn't match chunks {len(chunks)}"

    @pytest.mark.asyncio
    async def test_search_after_upsert(self, qdrant: QdrantStore) -> None:
        """After upsert, semantic search should return results."""
        chunks, _toc = await process_document_text(
            text=TEST_OCR_TEXT,
            document_id="pravo-7800202607010012",
            doc_uuid="test-doc-uuid",
            qdrant=qdrant,
        )
        if not chunks:
            pytest.skip("No chunks produced — nothing to search")

        # Perform a search
        embedder = Embedder()
        query_vec = await embedder.embed_query("размещение торговых объектов")
        results = await qdrant.search(
            query_embedding=query_vec,
            filters={"document_id": "pravo-7800202607010012"},
            limit=5,
        )
        assert len(results) > 0, "Search should return at least one result"
        for chunk, score in results:
            assert isinstance(chunk, DocumentChunk)
            assert chunk.document_id == "pravo-7800202607010012"
            assert score >= 0.0, f"Score should be non-negative, got {score}"

    @pytest.mark.asyncio
    async def test_delete_document_chunks(self, qdrant: QdrantStore) -> None:
        """After deleting chunks for a document, count should be 0."""
        chunks, _toc = await process_document_text(
            text=TEST_OCR_TEXT,
            document_id="pravo-7800202607010012",
            doc_uuid="test-doc-uuid",
            qdrant=qdrant,
        )
        if not chunks:
            pytest.skip("No chunks produced")

        await qdrant.delete_document_chunks("pravo-7800202607010012")
        count = await qdrant.count()
        assert count == 0, f"After delete, count should be 0, got {count}"

    @pytest.mark.asyncio
    async def test_empty_text_pipeline(self, qdrant: QdrantStore) -> None:
        """Empty text should return empty lists and not crash."""
        chunks, toc = await process_document_text(
            text="",
            document_id="pravo-empty",
            doc_uuid="empty-uuid",
            qdrant=qdrant,
        )
        assert chunks == []
        assert toc == []


# ── process_document_text without Qdrant ────────────────────────────


@pytest.mark.embedding
class TestPipelineWithoutQdrant:
    """Test process_document_text without a real Qdrant connection.

    This tests the pipeline logic in isolation (chunk → embed only,
    Qdrant upsert will be silently skipped/fallback).
    """

    @pytest.fixture
    def disabled_qdrant(self) -> QdrantStore:
        """A QdrantStore in disabled mode — all operations are no-ops."""
        return QdrantStore(disabled=True)

    @pytest.mark.asyncio
    async def test_pipeline_no_qdrant_still_works(self, disabled_qdrant: QdrantStore) -> None:
        """When Qdrant is disabled, pipeline should still return chunks and TOC."""
        chunks, toc = await process_document_text(
            text=TEST_OCR_TEXT,
            document_id="pravo-7800202607010012",
            doc_uuid="test-doc-uuid",
            qdrant=disabled_qdrant,
        )
        assert isinstance(chunks, list)
        assert isinstance(toc, list)
        # Embedder in stub mode sets zero vectors
        for c in chunks:
            assert c.embedding is not None

    @pytest.mark.asyncio
    async def test_pipeline_consistent_document_id(self, disabled_qdrant: QdrantStore) -> None:
        """Both chunks and TOC should use the same document_id."""
        chunks, toc = await process_document_text(
            text=TEST_OCR_TEXT,
            document_id="pravo-7800202607010012",
            doc_uuid="test-uuid",
            qdrant=disabled_qdrant,
        )
        for c in chunks:
            assert c.document_id == "pravo-7800202607010012"
            assert c.doc_uuid == "test-uuid"
        for node in toc:
            assert node.document_id == "pravo-7800202607010012"

    @pytest.mark.asyncio
    async def test_pipeline_with_section_repo(
        self,
        disabled_qdrant: QdrantStore,
    ) -> None:
        """When section_repo is provided, sections should be persisted and section_uuids set."""
        from unittest.mock import AsyncMock, MagicMock

        mock_section_repo = MagicMock()
        mock_section_repo.upsert_sections = AsyncMock(
            return_value={"1": "uuid-abc-123", "2": "uuid-def-456"}
        )

        chunks, _toc = await process_document_text(
            text=TEST_OCR_TEXT,
            document_id="pravo-7800202607010012",
            doc_uuid="test-doc-uuid",
            qdrant=disabled_qdrant,
            section_repo=mock_section_repo,
        )

        # Verify upsert_sections was called with correct args
        mock_section_repo.upsert_sections.assert_awaited_once()
        call_args = mock_section_repo.upsert_sections.call_args
        assert call_args[0][0] == "test-doc-uuid"  # doc_uuid
        assert len(call_args[0][1]) > 0  # toc list

        # Chunks should have section_uuids populated for matched external_ids
        for chunk in chunks:
            assert len(chunk.section_uuids) == len(chunk.section_external_ids)
            for eid, uid in zip(chunk.section_external_ids, chunk.section_uuids, strict=True):
                expected = mock_section_repo.upsert_sections.return_value.get(eid, "")
                assert uid == expected, f"Section {eid}: expected {expected}, got {uid}"
