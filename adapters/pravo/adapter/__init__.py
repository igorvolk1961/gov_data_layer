"""PravoAdapter — адаптер для источника данных pravo.gov.ru.

Uses the Strategy Pattern: each protocol method is delegated to a handler
instantiated based on the adapter's mode ('stub' or 'production').

Handlers live in:
- adapters/pravo/adapter/handlers/ — abstract base classes
- adapters/pravo/adapter/production/ — production implementations
- adapters/pravo/adapter/stub/ — stub implementations

To remove stub support entirely, delete the stub/ subpackage and remove
the 'stub' case from _build_handlers().
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from adapters.pravo.adapter.base import PravoAdapterBase
from adapters.pravo.adapter.handlers import (
    BaseGetContentHandler,
    BaseGetHandler,
    BaseGetTocHandler,
    BaseIngestHandler,
    BaseListTopicsHandler,
    BaseSearchHandler,
)
from adapters.pravo.adapter.production import (
    ProductionGetContentHandler,
    ProductionGetHandler,
    ProductionIngestHandler,
    ProductionListTopicsHandler,
    ProductionSearchHandler,
)
from adapters.pravo.adapter.stub import (
    StubGetContentHandler,
    StubGetHandler,
    StubGetTocHandler,
    StubIngestHandler,
    StubListTopicsHandler,
    StubSearchHandler,
)
from core.models.models import (
    OfficialDocument,
    SearchContext,
    SearchResult,
    TocNode,
    TopicNode,
)

if TYPE_CHECKING:
    from adapters.ocr.ocr_provider import OCRProvider
    from adapters.pravo.pravo_client import PravoClient
    from adapters.pravo.pravo_parser import PravoParser
    from core.observability.tracer import Tracer


class PravoAdapter(PravoAdapterBase):
    """Adapter for the pravo.gov.ru data source.

    Implements the SourceAdapter Protocol using the Strategy Pattern.
    Each protocol method delegates to a handler selected at construction
    time based on self._mode ('stub' or 'production').

    To add a new handler:
    1. Create an abstract base in handlers/
    2. Create production/ and stub/ implementations
    3. Add the handler attribute in __init__
    4. Add the delegation method
    """

    def __init__(
        self,
        mode: str | None = None,
        *,
        client: PravoClient | None = None,
        parser: PravoParser | None = None,
        ocr_provider: OCRProvider | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        """Initialize PravoAdapter and build handlers for the given mode.

        When mode is None (not explicitly passed), reads from the
        PRAVO_MODE environment variable. Falls back to 'production'.

        Args:
            mode: Operation mode ('stub' or 'production'). If None, reads
                  from PRAVO_MODE env var (default: 'production').
            client: External HTTP client (for testing).
            parser: External parser (for testing).
            ocr_provider: Optional OCR provider (for get_content in production).
            tracer: Optional tracer for observability.
        """
        if mode is None:
            mode = os.getenv("PRAVO_MODE", "production")
        super().__init__(
            mode=mode,
            client=client,
            parser=parser,
            ocr_provider=ocr_provider,
            tracer=tracer,
        )
        self._search_handler: BaseSearchHandler
        self._get_handler: BaseGetHandler
        self._ingest_handler: BaseIngestHandler
        self._list_topics_handler: BaseListTopicsHandler
        self._get_content_handler: BaseGetContentHandler
        self._get_toc_handler: BaseGetTocHandler

        self._build_handlers()

    def _build_handlers(self) -> None:
        """Instantiate handlers based on the current mode.

        Each handler receives a reference to this adapter so it can
        access shared resources (_pravo_client, _parser, _document_cache,
        tracer, etc.).
        """
        if self._mode == "stub":
            self._search_handler = StubSearchHandler(self)
            self._get_handler = StubGetHandler(self)
            self._ingest_handler = StubIngestHandler(self)
            self._list_topics_handler = StubListTopicsHandler(self)
            self._get_content_handler = StubGetContentHandler(self)
            self._get_toc_handler = StubGetTocHandler(self)
        else:
            self._search_handler = ProductionSearchHandler(self)
            self._get_handler = ProductionGetHandler(self)
            self._ingest_handler = ProductionIngestHandler(self)
            self._list_topics_handler = ProductionListTopicsHandler(self)
            self._get_content_handler = ProductionGetContentHandler(self)
            self._get_toc_handler = StubGetTocHandler(self)  # No production TOC yet

    # ----- SourceAdapter Protocol Methods -----

    async def search(
        self,
        query: str,
        context: SearchContext | None = None,
    ) -> list[SearchResult]:
        """Search documents.

        Delegates to the mode-specific search handler.
        """
        return await self._search_handler.search(query, context)

    async def get(self, document_id: str) -> OfficialDocument:
        """Get document by ID.

        Delegates to the mode-specific get handler.
        """
        return await self._get_handler.get(document_id)

    async def ingest(self) -> int:
        """Ingest documents.

        Delegates to the mode-specific ingest handler.
        """
        return await self._ingest_handler.ingest()

    async def list_topics(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[TopicNode]:
        """List rubricator topics.

        Delegates to the mode-specific list_topics handler.
        """
        return await self._list_topics_handler.list_topics(parent_id=parent_id, query=query)

    async def get_content(self, document_id: str) -> str:
        """Get full document text.

        Delegates to the mode-specific get_content handler.
        """
        return await self._get_content_handler.get_content(document_id)

    async def get_toc(
        self,
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> list[TocNode]:
        """Get document table of contents.

        Delegates to the mode-specific get_toc handler.
        """
        return await self._get_toc_handler.get_toc(
            document_id,
            parent_section_id=parent_section_id,
            query=query,
        )


__all__ = [
    "PravoAdapter",
]
