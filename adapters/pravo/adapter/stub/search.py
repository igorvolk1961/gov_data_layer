"""StubSearchHandler — stub search over cached documents."""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.pravo.adapter.handlers import BaseSearchHandler
from core.models.models import (
    ConfidenceSignals,
    SearchContext,
    SearchResult,
    SourceAvailability,
)


class StubSearchHandler(BaseSearchHandler):
    """Search over cached documents (populated by real HTTP calls)."""

    async def search(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> list[SearchResult]:
        """Search over cached documents.

        Args:
            query: Search query (case-insensitive substring match).
            context: Optional filtering parameters.

        Returns:
            List of search results.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.search",
            source_id=adapter.source_id,
            mode="stub",
            query=query,
        ) as span:
            span.set_input({"query": query, "context": context.model_dump() if context else None})
            now = datetime.now(timezone.utc)
            results: list[SearchResult] = []

            for doc, _ in adapter._document_cache.values():
                # Filter by query
                if query:
                    query_lower = query.lower()
                    if (
                        query_lower not in doc.title.lower()
                        and query_lower not in (doc.summary or "").lower()
                    ):
                        continue

                # Filter by context
                if context is not None:
                    if context.region and doc.region != context.region:
                        continue
                    if context.topic and not any(t in doc.topic for t in context.topic):
                        continue
                    if context.organization and not any(
                        o in doc.organization for o in context.organization
                    ):
                        continue

                results.append(
                    SearchResult(
                        id=doc.id,
                        title=doc.title,
                        snippet=(doc.summary or "")[:200],
                        url=doc.url,
                        source_name=doc.source.name,
                        jurisdiction=doc.jurisdiction,
                        region=doc.region,
                        topic=doc.topic,
                        organization=doc.organization,
                        ingest_date=doc.ingest_date,
                        legal_status=doc.legal_status,
                        confidence=ConfidenceSignals(
                            retrieval_relevance=0.95,
                            data_freshness=now,
                            source_availability=SourceAvailability.AVAILABLE,
                        ),
                    )
                )

            span.set_output({"count": len(results)})
            return results


__all__ = [
    "StubSearchHandler",
]
