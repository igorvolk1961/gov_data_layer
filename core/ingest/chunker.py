"""DocStructSplitter — структурный чанкинг для русских НПА.

Использует ChunkingOrchestrator из smart_chunker, который за один проход
(один parse_hierarchy + один generate_chunks) возвращает и sections, и chunks.
Оба результата (TocNode[] и DocumentChunk[]) получаются из одного парсинга текста.

ChunkingOrchestrator использует spaCy (CPU-bound), поэтому process_text()
запускается в thread pool executor.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from smart_chunker import ChunkingOrchestrator as _ChunkingOrchestrator

from core.models.models import DocumentChunk, TocNode

logger = logging.getLogger(__name__)


# ── DocStructSplitter — основной класс ────────────────────────────────


class DocStructSplitter:
    """Структурный чанкинг для русских НПА через ChunkingOrchestrator.

    split_text() — async, т.к. ChunkingOrchestrator использует spaCy (CPU-bound)
    и запускается в thread pool executor.

    Возвращает (chunks, toc) — оба из одного парсинга текста.
    """

    def __init__(self, max_chunk_size: int = 1024, chunk_overlap: int = 200) -> None:
        self._max_chunk_size = max_chunk_size
        self._chunk_overlap = chunk_overlap
        self._orch: _ChunkingOrchestrator | None = None

    async def _ensure_chunker(self) -> None:
        """Lazy-init ChunkingOrchestrator (лёгкая операция, без блокировок)."""
        if self._orch is not None:
            return
        logger.info(
            "Initializing ChunkingOrchestrator (max_chunk_size=%d, overlap=%d)",
            self._max_chunk_size,
            self._chunk_overlap,
        )
        self._orch = _ChunkingOrchestrator(
            config={
                "max_chunk_size": self._max_chunk_size,
                "chunk_overlap": self._chunk_overlap,
                "target_level": 3,
            }
        )

    async def split_text(
        self,
        text: str,
        document_id: str,
        doc_uuid: str,
        section_uuids: dict[str, str] | None = None,
    ) -> tuple[list[DocumentChunk], list[TocNode]]:
        """Split document text into chunks and extract TOC.

        Args:
            text: Full document text (from OCR).
            document_id: External document ID (source_id-publish_id).
            doc_uuid: UUID of the document record in PostgreSQL.
            section_uuids: Optional mapping of external_id -> UUID for sections.

        Returns:
            Tuple of (chunks, toc):
            - chunks: list of DocumentChunk for Qdrant
            - toc: list of TocNode for API / DB
        """
        if not text:
            return [], []

        return await self._split_with_smart_chunker(text, document_id, doc_uuid, section_uuids)

    async def _split_with_smart_chunker(
        self,
        text: str,
        document_id: str,
        doc_uuid: str,
        _section_uuids: dict[str, str] | None,
    ) -> tuple[list[DocumentChunk], list[TocNode]]:
        """Split using ChunkingOrchestrator (blocking — runs in thread pool)."""
        await self._ensure_chunker()
        assert self._orch is not None

        loop = asyncio.get_event_loop()

        def _process() -> dict[str, Any]:
            assert self._orch is not None
            return self._orch.process_text(text)  # type: ignore[no-any-return]

        result = await loop.run_in_executor(None, _process)

        raw_sections: list[dict[str, Any]] = result.get("sections", [])
        raw_chunks: list[dict[str, Any]] = result.get("chunks", [])

        # Строим lookup: section_number -> section_data (для section_path)
        sec_map: dict[str, dict[str, Any]] = {}
        for s in raw_sections:
            sec_map[str(s["number"])] = s

        # Sections -> TocNode
        toc = self._sections_to_toc(raw_sections, document_id)

        # Chunks -> DocumentChunk (with section_path via parent chain)
        chunks = self._chunks_to_doc_chunks(raw_chunks, sec_map, document_id, doc_uuid)

        return (chunks, toc)

    @staticmethod
    def _sections_to_toc(
        sections: list[dict[str, Any]],
        document_id: str,
    ) -> list[TocNode]:
        """Convert serialized Section dicts to TocNode list."""
        toc: list[TocNode] = []
        for sec in sections:
            parent_num = sec.get("parent_number")
            parent_id = str(parent_num) if parent_num is not None else ""
            toc.append(
                TocNode(
                    id=str(sec["number"]),
                    document_id=document_id,
                    title=str(sec.get("title", "")),
                    parent_id=parent_id,
                    level=int(sec.get("level", 0)),
                    child_count=len(sec.get("children", [])),
                )
            )
        return toc

    @staticmethod
    def _chunks_to_doc_chunks(
        chunks: list[dict[str, Any]],
        sec_map: dict[str, dict[str, Any]],
        document_id: str,
        doc_uuid: str,
    ) -> list[DocumentChunk]:
        """Convert serialized Chunk dicts to DocumentChunk list."""
        result: list[DocumentChunk] = []
        for i, ch in enumerate(chunks):
            meta = ch.get("metadata", {})
            sec_num = str(meta.get("section_number", ""))

            # Строим section_path через parent_number chain
            path: list[str] = []
            cur = sec_map.get(sec_num)
            while cur is not None:
                num = cur.get("number", "")
                title = cur.get("title", "")
                label = f"{num}. {title}".strip(". ")
                path.insert(0, label)
                parent_num = cur.get("parent_number")
                cur = sec_map.get(str(parent_num)) if parent_num is not None else None

            result.append(
                DocumentChunk(
                    id=str(meta.get("chunk_id", str(uuid.uuid4()))),
                    document_id=document_id,
                    doc_uuid=doc_uuid,
                    text=str(ch.get("content", "")),
                    section_path=path,
                    section_external_ids=[],
                    section_uuids=[],
                    chunk_index=i,
                )
            )
        return result


__all__ = [
    "DocStructSplitter",
]
