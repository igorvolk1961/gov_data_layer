"""ProductionSearchHandler — production search via pravo.gov.ru API."""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseSearchHandler
from core.models.models import SearchContext, SearchResult
from core.observability.logger import get_logger

logger = get_logger(__name__)


class ProductionSearchHandler(BaseSearchHandler):
    """Search documents using the real pravo.gov.ru API."""

    async def search(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> list[SearchResult]:
        """Search via pravo.gov.ru API.

        Args:
            query: Search query.
            context: Optional filtering parameters.

        Returns:
            List of search results.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.search",
            source_id=adapter.source_id,
            mode="production",
            query=query,
        ) as span:
            span.set_input({"query": query, "context": context.model_dump() if context else None})
            # TODO: Implement production search via API
            logger.warning("Production search not yet implemented — returning empty results")
            results: list[SearchResult] = []
            span.set_output({"count": len(results)})
            return results


__all__ = [
    "ProductionSearchHandler",
]
