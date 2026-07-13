"""ProductionIngestHandler — production ingest via pravo.gov.ru API."""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.pravo.adapter.constants import _INGEST_PAGE_SIZE
from adapters.pravo.adapter.handlers import BaseIngestHandler
from core.errors import SourceUnavailableError
from core.observability.logger import get_logger

logger = get_logger(__name__)


class ProductionIngestHandler(BaseIngestHandler):
    """Ingest documents using the real pravo.gov.ru API."""

    async def ingest(self) -> int:
        """Ingest documents in production mode.

        Fetches recent documents via API, parses them, and caches.

        Returns:
            Number of ingested documents.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.ingest",
            source_id=adapter.source_id,
            mode="production",
        ) as span:
            # Production: fetch recent documents via API
            await adapter._ensure_caches_populated()
            try:
                result = await adapter._pravo_client.search_documents(
                    params={"pageSize": _INGEST_PAGE_SIZE, "sort": "publishDate"}
                )
                items = result.get("items", [])
                count = 0
                for raw in items:
                    try:
                        doc = adapter._parser.parse_search_result(raw)
                        adapter._document_cache[doc.id] = (doc, datetime.now(timezone.utc))
                        count += 1
                    except (ValueError, KeyError, TypeError) as exc:
                        logger.warning("Failed to parse ingest item: %s", exc)
                        continue
                span.set_output({"count": count, "mode": "production"})
                logger.info("Ingested %d documents from pravo.gov.ru", count)
                return count
            except SourceUnavailableError:
                circuit_state = adapter._pravo_client.circuit_state
                logger.warning(
                    "Ingest failed — API unavailable (circuit: %s)",
                    circuit_state,
                )
                span.set_output(
                    {"count": 0, "error": "source_unavailable", "circuit_state": circuit_state}
                )
                return 0


__all__ = [
    "ProductionIngestHandler",
]
