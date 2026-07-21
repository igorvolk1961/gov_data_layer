"""ProductionIngestHandler — production ingest via pravo.gov.ru API.

Fetches documents from API, then runs the shared pipeline:
metadata → OCR → TOC → chunk → embed → Qdrant.
Sections are persisted to PostgreSQL via the shared pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.base.ingest_pipeline import process_document_text
from adapters.pravo.adapter.constants import _INGEST_BLOCKS, _INGEST_PAGE_SIZE
from adapters.pravo.adapter.handlers import BaseIngestHandler
from core.errors import SourceUnavailableError


class ProductionIngestHandler(BaseIngestHandler):
    """Ingest documents using the real pravo.gov.ru API."""

    async def ingest(self) -> int:
        """Ingest documents in production mode.

        Full pipeline: fetch metadata → cache → persist to DB →
        OCR → TOC → chunk → embed → Qdrant (with section persistence).

        Returns:
            Number of successfully ingested documents.
        """
        return await self._ingest_with_blocks(_INGEST_BLOCKS)

    async def _ingest_with_blocks(self, blocks: dict[str, str]) -> int:
        """Ingest documents for given blocks (overridable for testing)."""
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.ingest",
            source_id=adapter.source_id,
            mode="production",
        ) as span:
            await adapter._ensure_caches_populated()

            # Create section_repo if DB is available
            section_repo = None
            if adapter._db is not None:
                from core.persistence.repository import SectionRepository

                section_repo = SectionRepository(adapter._db)

            # Create required pipeline components
            from core.api.app_config import get_config
            from core.index.qdrant_store import QdrantStore
            from core.ingest.chunker import DocStructSplitter
            from core.ingest.embedder import Embedder

            cfg = get_config()
            chunker = DocStructSplitter()
            embedder = Embedder(
                model_name=cfg.embedding.model, vector_size=cfg.embedding.vector_size
            )
            qdrant = QdrantStore(
                host=cfg.qdrant_host, port=cfg.qdrant_port, vector_size=cfg.embedding.vector_size
            )

            total_count = 0
            total_errors: list[str] = []

            # Перебираем блоки публикации. Для каждого блока известна
            # юрисдикция, которую получают все документы из этого блока.
            for block_code, jurisdiction in blocks.items():
                block_span_name = f"pravo.ingest.block.{block_code or 'all'}"
                with adapter.tracer.trace(block_span_name) as block_span:
                    block_span.set_input({"block": block_code, "jurisdiction": jurisdiction})

                    # Устанавливаем юрисдикцию в парсере — она попадёт
                    # во все документы, распарсенные в этом цикле блока.
                    adapter._parser.set_jurisdiction(jurisdiction)

                    # Формируем параметры поиска для этого блока
                    search_params: dict[str, object] = {
                        "pageSize": _INGEST_PAGE_SIZE,
                        "sort": "publishDate",
                    }
                    if block_code is not None:
                        search_params["Block"] = block_code

                    try:
                        result = await adapter._pravo_client.search_documents(
                            params=search_params,
                        )
                        items = result.get("items", [])
                        block_count = 0
                        for raw in items:
                            try:
                                doc = adapter._parser.parse_search_result(raw)
                                document_id = doc.id
                                adapter._document_cache[document_id] = (
                                    doc,
                                    datetime.now(timezone.utc),
                                )

                                # Persist to DB and get doc_uuid
                                await adapter._persist_document(doc)
                                doc_uuid = (
                                    await self._get_doc_uuid(doc.publish_id)
                                    if doc.publish_id
                                    else ""
                                )

                                # Get text via OCR
                                text = await adapter.get_content(document_id)  # type: ignore[attr-defined]

                                # Run shared pipeline: chunk → sections → embed → link topics → Qdrant
                                await process_document_text(
                                    text,
                                    document_id,
                                    doc_uuid,
                                    chunker=chunker,
                                    embedder=embedder,
                                    qdrant=qdrant,
                                    section_repo=section_repo,
                                )

                                block_count += 1
                            except (ValueError, KeyError, TypeError) as exc:
                                with adapter.tracer.trace("pravo.ingest.item_error") as item_span:
                                    item_span.set_input({"document_id": document_id})
                                    item_span.set_error(exc)
                                continue
                            except Exception as exc:
                                with adapter.tracer.trace(
                                    "pravo.ingest.pipeline_error"
                                ) as pipe_span:
                                    pipe_span.set_input({"document_id": document_id})
                                    pipe_span.set_error(exc)
                                total_errors.append(str(exc))
                                continue

                        block_span.set_output({"count": block_count, "block": block_code})
                        total_count += block_count

                    except SourceUnavailableError:
                        circuit_state = adapter._pravo_client.circuit_state
                        block_span.set_output(
                            {
                                "count": 0,
                                "error": "source_unavailable",
                                "circuit_state": circuit_state,
                                "block": block_code,
                            }
                        )
                        # Continue to next block (graceful degradation)
                        continue

            # Сбрасываем юрисдикцию после завершения инжеста
            adapter._parser.set_jurisdiction(None)

            span.set_output({"count": total_count, "errors": total_errors})
            return total_count

    async def _get_doc_uuid(self, publish_id: str) -> str:
        """Get document UUID from DB after persistence (real UUID, not external ID)."""
        db = self._adapter._db
        if db is None:
            return ""
        row = await db.fetchval(
            "SELECT id FROM document WHERE publish_id = $1",
            publish_id,
        )
        return str(row) if row else ""


__all__ = [
    "ProductionIngestHandler",
]
