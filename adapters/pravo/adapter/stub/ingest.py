"""StubIngestHandler — ingest documents via real HTTP for fixed publish_ids.

Fetches each document from the real API, then runs the shared pipeline:
metadata → OCR → TOC → chunk → embed → Qdrant.
Sections are persisted to PostgreSQL via the shared pipeline.
"""

from __future__ import annotations

from adapters.base.ingest_pipeline import process_document_text
from adapters.pravo.adapter.handlers import BaseIngestHandler
from adapters.pravo.adapter.stub._data import _STUB_PUBLISH_IDS_INITIAL


class StubIngestHandler(BaseIngestHandler):
    """Ingest documents from the fixed stub publish_id list.

    Uses real API calls for metadata and OCR, then runs the shared
    pipeline (chunk → embed → Qdrant with section persistence) — same
    as production mode.
    """

    async def ingest(self) -> int:
        """Fetch all stub documents and run the full pipeline.

        Iterates over _STUB_PUBLISH_IDS_INITIAL, calls adapter.get()
        for each one, runs OCR, chunks, embeds, and stores in Qdrant.
        Sections are persisted to PostgreSQL if DB is configured.

        Returns:
            Number of documents successfully processed.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.ingest",
            source_id=adapter.source_id,
            mode="stub",
        ) as span:
            # Create section_repo if DB is available
            section_repo = None
            if adapter._db is not None:
                from core.persistence.repository import SectionRepository

                section_repo = SectionRepository(adapter._db)

            count = 0
            errors: list[str] = []
            for publish_id in _STUB_PUBLISH_IDS_INITIAL:
                document_id = f"pravo-{publish_id}"
                try:
                    # 1. Get metadata (also persists to DB via _persist_document)
                    await adapter.get(document_id)  # type: ignore[attr-defined]

                    # 2. Get doc_uuid from DB
                    doc_repo = adapter._doc_repo_lazy
                    doc_uuid = ""
                    if doc_repo is not None:
                        db_doc = await doc_repo.get_document_by_publish_id(publish_id)
                        if db_doc:
                            doc_uuid = db_doc.id

                    # 3. Get text via OCR (from cache in stub mode)
                    text = await adapter.get_content(document_id)  # type: ignore[attr-defined]

                    # 4. Run shared pipeline: chunk → persist sections → embed → Qdrant
                    await process_document_text(
                        text,
                        document_id,
                        doc_uuid,
                        section_repo=section_repo,
                    )

                    count += 1
                except Exception as exc:
                    with adapter.tracer.trace("pravo.ingest.item_error") as item_span:
                        item_span.set_input({"document_id": document_id})
                        item_span.set_error(exc)
                    errors.append(str(exc))

            span.set_output({"count": count, "errors": errors})
            return count


__all__ = [
    "StubIngestHandler",
]
