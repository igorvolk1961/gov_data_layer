"""PravoAdapterBase — shared logic for PravoAdapter.

Contains the constructor, cache management, resource lifecycle,
and utility methods common to both stub and production modes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from adapters.base import RSSAdapter
from adapters.pravo.adapter.constants import (
    _CACHE_POPULATE_TTL,
    _STALE_CACHE_TTL,
)
from adapters.pravo.pravo_client import PravoClient
from adapters.pravo.pravo_parser import PravoParser
from core.errors import SourceUnavailableError
from core.models.models import (
    OfficialDocument,
    TocNode,
    TopicNode,
)
from core.observability.logger import get_logger

if TYPE_CHECKING:
    from adapters.ocr.ocr_provider import OCRProvider
    from core.observability.tracer import Tracer

logger = get_logger(__name__)


class PravoAdapterBase(RSSAdapter):
    """Base adapter class for pravo.gov.ru data source.

    Provides shared logic: constructor, cache management, resource lifecycle,
    and utility methods used by both stub and production handlers.

    Subclasses (PravoAdapter) add mode-specific handler selection.
    """

    def __init__(
        self,
        mode: str = "stub",
        *,
        client: PravoClient | None = None,
        parser: PravoParser | None = None,
        ocr_provider: OCRProvider | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        """Initialize PravoAdapterBase.

        Args:
            mode: Operation mode ('stub' or 'production').
            client: External HTTP client (for testing).
            parser: External parser (for testing).
            ocr_provider: Optional OCR provider (for get_content in production).
            tracer: Optional tracer for observability.
        """
        # RSS feed for pravo.gov.ru (stub for now).
        # TODO: Replace feed_url with the real pravo.gov.ru RSS feed URL
        # after RSS monitoring integration (Day 2).
        super().__init__(
            feed_url="",
            timeout=30.0,
            max_retries=3,
            tracer=tracer,
        )

        self._mode = mode
        self._pravo_client = client or PravoClient(tracer=tracer)
        self._parser = parser or PravoParser()
        self._ocr_provider = ocr_provider

        # Stale document cache: {document_id: (OfficialDocument, cache_time)}
        # Used as fallback when the API is unavailable.
        self._document_cache: dict[str, tuple[OfficialDocument, datetime]] = {}

        # Cache population tracking: when were caches last refreshed?
        self._cache_populated_at: datetime | None = None

    @property
    def source_id(self) -> str:
        return "pravo"

    # ----- SourceAdapter Protocol Methods (shared) -----

    async def normalize(self, raw: dict[str, object]) -> OfficialDocument:
        """Normalize raw source data to the canonical model.

        Args:
            raw: Raw data from the pravo.gov.ru API.

        Returns:
            Normalized document.

        Raises:
            InvalidInputError: Invalid data.
        """
        return self._parser.parse_document(raw)

    async def get_toc(
        self,
        _document_id: str,
        _parent_section_id: str | None = None,
        _query: str = "",
    ) -> list[TocNode]:
        """Get document table of contents.

        Stub — TOC extraction from PDF is not implemented at this stage.

        Args:
            _document_id: Document ID.
            _parent_section_id: Parent section ID.
            _query: Optional search query.

        Returns:
            Empty list (stub).
        """
        return []

    # ----- Resource Management -----

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        await self._pravo_client.close()

    async def __aenter__(self) -> PravoAdapterBase:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ----- RSSAdapter Protocol Methods -----

    async def parse_entry(self, raw_entry: dict[str, Any]) -> dict[str, Any]:
        """Parse a single RSS entry into raw data for normalization.

        Args:
            raw_entry: Raw entry from RSS/Atom feed.

        Returns:
            Dictionary with raw data ready for normalize().
        """
        # Stub: pravo.gov.ru RSS feed will be integrated later
        return raw_entry

    # ----- Private Utility Methods -----

    def _extract_publish_id(self, document_id: str) -> str:
        """Extract publish_id (eoNumber) from document_id.

        Supports formats:
        - 'pravo-0001202012230060' -> '0001202012230060'
        - '0001202012230060' -> '0001202012230060'

        Args:
            document_id: Document ID.

        Returns:
            Electronic publication number.
        """
        if document_id.startswith("pravo-"):
            return document_id[len("pravo-") :]
        return document_id

    def _get_stale_cached(self, document_id: str) -> OfficialDocument | None:
        """Return a stale cached document if available and within TTL.

        Args:
            document_id: Document identifier.

        Returns:
            Cached document if found and not expired, None otherwise.
        """
        entry = self._document_cache.get(document_id)
        if entry is None:
            return None
        doc, cache_time = entry
        age = (datetime.now(timezone.utc) - cache_time).total_seconds()
        if age > _STALE_CACHE_TTL:
            # Cache entry expired — remove it
            del self._document_cache[document_id]
            return None
        return doc

    async def _ensure_caches_populated(self) -> None:
        """Populate parser caches (authorities, doc types) if stale or empty.

        Fetches lookup data from the API and updates the parser's caches
        so that document_type and organization fields resolve correctly.
        Caches are refreshed at most once per _CACHE_POPULATE_TTL.
        """
        now = datetime.now(timezone.utc)
        if self._cache_populated_at is not None:
            age = (now - self._cache_populated_at).total_seconds()
            if age < _CACHE_POPULATE_TTL:
                return  # Still fresh

        try:
            # Fetch authorities and doc types for the first block/category
            blocks = await self._pravo_client.get_public_blocks()
            if not blocks:
                logger.warning("No public blocks found — cannot populate caches")
                return

            first_block = str(blocks[0].get("id", ""))
            if not first_block:
                return

            categories = await self._pravo_client.get_categories(block=first_block)
            if not categories:
                return

            first_category = str(categories[0].get("id", ""))
            if not first_category:
                return

            authorities = await self._pravo_client.get_signatory_authorities(
                block=first_block,
                category=first_category,
            )
            self._parser.update_authority_cache(authorities)

            if authorities:
                first_authority = str(authorities[0].get("id", ""))
                doc_types = await self._pravo_client.get_document_types(
                    block=first_block,
                    category=first_category,
                    authority_id=first_authority,
                )
                self._parser.update_doc_type_cache(doc_types)

            self._cache_populated_at = now
            logger.info(
                "Populated parser caches: %d authorities, %d doc types",
                len(authorities),
                len(self._parser._doc_type_cache),  # type: ignore[attr-defined]
            )
        except SourceUnavailableError:
            logger.warning("Failed to populate parser caches — API unavailable")
            # Don't update _cache_populated_at — will retry on next call

    def _get_ocr_provider(self) -> OCRProvider | None:
        """Get the OCR provider, creating it lazily from config if needed.

        Returns:
            OCRProvider instance, or None if no provider is configured.
        """
        if self._ocr_provider is not None:
            return self._ocr_provider

        # Lazy creation from config
        try:
            from core.api.app_config import get_config

            app_cfg = get_config()
            provider_name = app_cfg.ocr.provider

            if provider_name == "stub":
                from adapters.ocr.stub_ocr import StubOCR

                self._ocr_provider = StubOCR()
            elif provider_name == "tesseract":
                from adapters.ocr.tesseract_ocr import TesseractOCR

                self._ocr_provider = TesseractOCR(
                    lang=app_cfg.ocr.tesseract_lang,
                    timeout=app_cfg.ocr.tesseract_timeout,
                )
            elif provider_name == "yandex_vision":
                from adapters.ocr.yandex_vision import YandexVisionOCR

                self._ocr_provider = YandexVisionOCR.from_config()
            else:
                logger.warning(
                    "Unknown OCR provider '%s' — content extraction disabled", provider_name
                )
                return None

            return self._ocr_provider
        except Exception as exc:
            logger.warning("Failed to create OCR provider: %s", exc)
            return None

    @staticmethod
    def _blocks_to_topics(
        blocks: list[dict[str, Any]],
        parent_id: str,
    ) -> list[TopicNode]:
        """Convert API publication blocks to TopicNode.

        Args:
            blocks: List of blocks from /api/PublicBlocks.
            parent_id: Parent block ID.

        Returns:
            List of rubricator nodes.
        """
        topics: list[TopicNode] = []
        for block in blocks:
            block_id = str(block.get("id", ""))
            block_name = str(block.get("name", ""))
            if not block_id:
                continue
            topics.append(
                TopicNode(
                    id=block_id,
                    name=block_name,
                    parent_id=parent_id,
                    description=block.get("description"),
                    child_count=0,
                    document_count=0,
                )
            )
        return topics


__all__ = [
    "PravoAdapterBase",
]
