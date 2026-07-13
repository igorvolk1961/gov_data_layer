"""StubIngestHandler — ingest documents via real HTTP for fixed publish_ids.

In stub mode, the handler fetches each document from the real pravo.gov.ru
API using the fixed list of publish_ids defined in _data.py. This ensures
the full pipeline (HTTP → parse → model) is exercised even in stub mode.
"""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseIngestHandler
from adapters.pravo.adapter.stub._data import _STUB_PUBLISH_IDS_INITIAL
from core.observability.logger import get_logger

logger = get_logger(__name__)


class StubIngestHandler(BaseIngestHandler):
    """Ingest documents from the fixed stub publish_id list.

    For each publish_id in _STUB_PUBLISH_IDS_INITIAL, this handler
    calls adapter.get() which makes a real HTTP request to pravo.gov.ru,
    parses the response, and caches the result.
    """

    async def ingest(self) -> int:
        """Fetch all stub documents from the real API.

        Iterates over _STUB_PUBLISH_IDS_INITIAL, calls adapter.get()
        for each one, and returns the count of successfully fetched
        documents.

        Returns:
            Number of documents successfully ingested.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.ingest",
            source_id=adapter.source_id,
            mode="stub",
        ) as span:
            count = 0
            errors: list[str] = []
            for publish_id in _STUB_PUBLISH_IDS_INITIAL:
                document_id = f"pravo-{publish_id}"
                try:
                    # This calls StubGetHandler.get() which does real HTTP + parse
                    await adapter.get(document_id)  # type: ignore[attr-defined]
                    count += 1
                    logger.info("Ingested document '%s'", document_id)
                except Exception as exc:
                    logger.error("Failed to ingest document '%s': %s", document_id, exc)
                    errors.append(str(exc))

            span.set_output({"count": count, "errors": errors})
            if errors:
                logger.warning(
                    "Ingest completed with %d/%d successes, %d errors: %s",
                    count,
                    len(_STUB_PUBLISH_IDS_INITIAL),
                    len(errors),
                    errors,
                )
            return count


__all__ = [
    "StubIngestHandler",
]
