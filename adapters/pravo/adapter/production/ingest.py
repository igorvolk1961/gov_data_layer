"""ProductionIngestHandler — production ingest via pravo.gov.ru API.

Fetches documents from API, then runs the shared pipeline:
metadata → OCR → TOC → chunk → embed → Qdrant.
Sections are persisted to PostgreSQL via the shared pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.base.ingest_pipeline import process_document_text
from adapters.pravo.adapter.constants import _INGEST_PAGE_SIZE
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

            try:
                result = await adapter._pravo_client.search_documents(
                    params={"pageSize": _INGEST_PAGE_SIZE, "sort": "publishDate"}
                )
                items = result.get("items", [])
                count = 0
                errors: list[str] = []
                for raw in items:
                    try:
                        doc = adapter._parser.parse_search_result(raw)
                        document_id = doc.id
                        adapter._document_cache[document_id] = (doc, datetime.now(timezone.utc))

                        # Persist to DB and get doc_uuid
                        await adapter._persist_document(doc)
                        doc_uuid = (
                            await self._get_doc_uuid(doc.publish_id) if doc.publish_id else ""
                        )

                        # Get text via OCR
                        text = await adapter.get_content(document_id)  # type: ignore[attr-defined]

                        # Run shared pipeline: chunk → persist sections → embed → Qdrant
                        await process_document_text(
                            text,
                            document_id,
                            doc_uuid,
                            section_repo=section_repo,
                        )

                        count += 1
                    except (ValueError, KeyError, TypeError) as exc:
                        with adapter.tracer.trace("pravo.ingest.item_error") as item_span:
                            item_span.set_input({"document_id": document_id})
                            item_span.set_error(exc)
                        continue
                    except Exception as exc:
                        with adapter.tracer.trace("pravo.ingest.pipeline_error") as pipe_span:
                            pipe_span.set_input({"document_id": document_id})
                            pipe_span.set_error(exc)
                        errors.append(str(exc))
                        continue

                span.set_output({"count": count, "errors": errors})
                return count
            except SourceUnavailableError:
                circuit_state = adapter._pravo_client.circuit_state
                with adapter.tracer.trace("pravo.ingest.source_unavailable") as src_span:
                    src_span.set_output(
                        {
                            "count": 0,
                            "error": "source_unavailable",
                            "circuit_state": circuit_state,
                        }
                    )
                return 0

    async def _get_doc_uuid(self, publish_id: str) -> str:
        """Get document UUID from DB after persistence."""
        doc_repo = self._adapter._doc_repo_lazy
        if doc_repo is None:
            return ""
        doc = await doc_repo.get_document_by_publish_id(publish_id)
        return doc.id if doc else ""


__all__ = [
    "ProductionIngestHandler",
]
