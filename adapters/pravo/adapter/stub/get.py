"""StubGetHandler — document retrieval via real HTTP + parsing.

In stub mode, the handler fetches documents from the real pravo.gov.ru API
(just like production mode), but only for the fixed set of publish_ids
defined in _data.py. This ensures the full pipeline (HTTP → parse → model)
is exercised even in stub mode.
"""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.pravo.adapter.handlers import BaseGetHandler
from core.errors import NotFoundError, SourceUnavailableError
from core.models.models import OfficialDocument
from core.observability.logger import get_logger

logger = get_logger(__name__)


class StubGetHandler(BaseGetHandler):
    """Fetch a document by ID using the real pravo.gov.ru API.

    Unlike the old stub handler (which returned pre-built documents),
    this handler makes real HTTP calls and parses the response, just
    like ProductionGetHandler. The difference is that stub mode only
    works with the fixed set of publish_ids defined in _data.py.
    """

    async def get(self, document_id: str) -> OfficialDocument:
        """Get document by ID in stub mode.

        Fetches from the real API, caches on success, falls back to
        stale cache on SourceUnavailableError.

        Args:
            document_id: Document identifier.

        Returns:
            Full document model.

        Raises:
            NotFoundError: Document not found.
            SourceUnavailableError: Source unavailable and no stale cache.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.get",
            source_id=adapter.source_id,
            mode="stub",
            document_id=document_id,
        ) as span:
            span.set_input({"document_id": document_id})

            publish_id = adapter._extract_publish_id(document_id)
            try:
                raw = await adapter._pravo_client.get_document(publish_id)
                doc = adapter._parser.parse_document(raw)
                # Override the document ID to match the requested identifier
                # (parser generates pravo-{GUID}, but we want pravo-{publish_id})
                doc.id = document_id
                # Cache the document after successful fetch
                adapter._document_cache[document_id] = (doc, datetime.now(timezone.utc))
                span.set_output({"found": True, "publish_id": publish_id})
                return doc
            except SourceUnavailableError as exc:
                # Check if this was a 404 (document not found) vs real source error
                error_msg = str(exc)
                if "HTTP 404" in error_msg or "non-retryable HTTP status" in error_msg:
                    span.set_error(exc)
                    raise NotFoundError(f"Document '{document_id}' not found") from exc
                # Try stale cache before giving up for real source errors
                stale = adapter._get_stale_cached(document_id)
                circuit_state = adapter._pravo_client.circuit_state
                if stale is not None:
                    logger.warning(
                        "API unavailable for document '%s' (circuit: %s) — returning stale cache",
                        document_id,
                        circuit_state,
                    )
                    span.set_output(
                        {"found": True, "stale_cache": True, "circuit_state": circuit_state}
                    )
                    return stale
                raise SourceUnavailableError(
                    f"Source pravo.gov.ru unavailable (circuit: {circuit_state}) "
                    f"for document '{document_id}' — no stale cache available"
                ) from None
            except (ValueError, KeyError, TypeError) as exc:
                span.set_error(exc)
                raise NotFoundError(f"Failed to parse document '{document_id}': {exc}") from exc
            except Exception as exc:
                span.set_error(exc)
                raise SourceUnavailableError(
                    f"Unexpected error fetching document '{document_id}': {exc}"
                ) from exc


__all__ = [
    "StubGetHandler",
]
