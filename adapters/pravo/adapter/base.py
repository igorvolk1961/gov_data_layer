"""PravoAdapterBase — shared logic for PravoAdapter.

Contains the constructor, cache management, resource lifecycle,
and utility methods common to both stub and production modes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from adapters.base import RSSAdapter
from adapters.base.circuit_breaker import CircuitBreaker
from adapters.base.toc_mixin import TocMixin
from adapters.pravo.adapter.constants import (
    _CACHE_POPULATE_TTL,
    _STALE_CACHE_TTL,
)
from adapters.pravo.pravo_client import PravoClient
from adapters.pravo.pravo_parser import PravoParser
from core.errors import PersistenceUnavailableError, SourceUnavailableError
from core.models.models import (
    OfficialDocument,
    TocNode,
    TopicNode,
)
from core.observability.logger import get_logger
from core.persistence import DatabaseClient
from core.persistence.repository import DocumentRepository, ReferenceRepository

if TYPE_CHECKING:
    from adapters.ocr.ocr_provider import OCRProvider
    from core.observability.tracer import Tracer

logger = get_logger(__name__)


class PravoAdapterBase(RSSAdapter, TocMixin):
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
        db: DatabaseClient | None = None,
    ) -> None:
        """Initialize PravoAdapterBase.

        Args:
            mode: Operation mode ('stub' or 'production').
            client: External HTTP client (for testing).
            parser: External parser (for testing).
            ocr_provider: Optional OCR provider (for get_content in production).
            tracer: Optional tracer for observability.
            db: Optional DatabaseClient for PostgreSQL persistence.
                Required for production use; None allowed for tests
                that only verify the HTTP → parse → model pipeline.
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
        self._db = db

        # Circuit breaker for DB persistence (ingest path)
        self._persistence_cb = CircuitBreaker(
            name="db_persistence",
            failure_threshold=3,
            recovery_timeout=30.0,
        )

        # Stale document cache: {document_id: (OfficialDocument, cache_time)}
        # Used as fallback when the API is unavailable.
        self._document_cache: dict[str, tuple[OfficialDocument, datetime]] = {}

        # Cache population tracking: when were caches last refreshed?
        self._cache_populated_at: datetime | None = None

        # Lazy-init repositories
        self._ref_repo: ReferenceRepository | None = None
        self._doc_repo: DocumentRepository | None = None

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
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> list[TocNode]:
        """Extract document structure from OCR text.

        Mode-independent — uses shared extract_toc_from_text() from
        adapters/base/toc_extractor.py. Both stub and production modes
        use this same implementation.

        Args:
            document_id: Document identifier.
            parent_section_id: Optional parent section filter.
            query: Optional search query.

        Returns:
            List of TocNode objects.
        """
        from adapters.base.toc_extractor import extract_toc_from_text

        try:
            text = await self.get_content(document_id)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("Cannot get TOC for '%s': text extraction failed", document_id)
            return []

        return await extract_toc_from_text(text, document_id, parent_section_id, query)

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
                len(self._parser._doc_type_cache),
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
            elif provider_name == "demo_doc":
                from adapters.ocr.demo_doc_provider import DemoDocProvider

                self._ocr_provider = DemoDocProvider()
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

    @property
    def _ref_repo_lazy(self) -> ReferenceRepository | None:
        """Lazy init of ReferenceRepository (only if DB is available)."""
        if self._ref_repo is None and self._db is not None:
            self._ref_repo = ReferenceRepository(self._db)
        return self._ref_repo

    @property
    def _doc_repo_lazy(self) -> DocumentRepository | None:
        """Lazy init of DocumentRepository (only if DB is available)."""
        if self._doc_repo is None and self._db is not None:
            ref_repo = self._ref_repo_lazy
            assert ref_repo is not None
            self._doc_repo = DocumentRepository(self._db, ref_repo)
        return self._doc_repo

    async def _ensure_reference_names(self, doc: OfficialDocument) -> None:
        """Lazy-заполнение имён органов и типов документов из кэша парсера.

        Если кэш пуст — однократно загружает все справочные данные из API
        и устанавливает doc.organization / doc.document_type из кэша.
        """
        parser = self._parser

        # --- Организация ---
        if doc.organization_id and not doc.organization:
            if not parser._authority_cache:
                await self._lazy_load_authorities()
            doc.organization = parser._authority_cache.get(doc.organization_id)

        # --- Тип документа ---
        if doc.document_type_id and not doc.document_type:
            if not parser._doc_type_cache:
                await self._lazy_load_doc_types(doc.organization_id)
            doc.document_type = parser._doc_type_cache.get(doc.document_type_id)

    async def _lazy_load_authorities(self) -> None:
        """Загрузить все органы из API в кэш парсера."""
        try:
            blocks = await self._pravo_client.get_public_blocks()
            if not blocks:
                return
            block_id = str(blocks[0].get("id", ""))
            if not block_id:
                return
            categories = await self._pravo_client.get_categories(block=block_id)
            if not categories:
                return
            cat_id = str(categories[0].get("id", ""))
            if not cat_id:
                return
            authorities = await self._pravo_client.get_signatory_authorities(
                block=block_id,
                category=cat_id,
            )
            self._parser.update_authority_cache(authorities)
        except SourceUnavailableError:
            logger.warning("Failed to load authorities — API unavailable")

    async def _lazy_load_doc_types(self, authority_id: str | None) -> None:
        """Загрузить все типы документов из API в кэш парсера."""
        try:
            blocks = await self._pravo_client.get_public_blocks()
            if not blocks:
                return
            block_id = str(blocks[0].get("id", ""))
            if not block_id:
                return
            categories = await self._pravo_client.get_categories(block=block_id)
            if not categories:
                return
            cat_id = str(categories[0].get("id", ""))
            if not cat_id:
                return
            doc_types = await self._pravo_client.get_document_types(
                block=block_id,
                category=cat_id,
                authority_id=authority_id or "",
            )
            self._parser.update_doc_type_cache(doc_types)
        except SourceUnavailableError:
            logger.warning("Failed to load doc types — API unavailable")

    async def _persist_document(self, doc: OfficialDocument) -> None:
        """Persist a canonical document to PostgreSQL if DB is configured.

        If DatabaseClient is not configured (self._db is None), logs a warning
        and returns. If configured, persistence is mandatory — errors propagate
        to the caller.

        Uses CircuitBreaker for the ingest path: after 3 consecutive failures
        the circuit opens and raises PersistenceUnavailableError immediately
        without calling the DB.

        Args:
            doc: The canonical OfficialDocument to persist.

        Raises:
            PersistenceUnavailableError: If circuit breaker is OPEN.
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        if not self._persistence_cb.can_request():
            logger.warning(
                "Persistence circuit breaker is OPEN — skipping persistence for %s",
                doc.id,
            )
            raise PersistenceUnavailableError(
                f"Persistence circuit breaker is OPEN for document {doc.id}",
            )

        if self._db is None:
            logger.warning(
                "Database not configured — skipping persistence for document %s",
                doc.id,
            )
            return

        try:
            await self._db.connect()

            ref_repo = self._ref_repo_lazy
            doc_repo = self._doc_repo_lazy
            assert ref_repo is not None
            assert doc_repo is not None

            # Get or create data source
            source_uuid = await ref_repo.get_or_create_data_source(
                source_id=self.source_id,
                name=doc.source.name,
                url=doc.url,
            )

            # Lazy-заполнение имён справочных записей перед upsert
            await self._ensure_reference_names(doc)

            # Upsert the document
            await doc_repo.upsert_document(doc, source_uuid)

            self._persistence_cb.record_success()
        except Exception:
            self._persistence_cb.record_failure()
            raise


__all__ = [
    "PravoAdapterBase",
]
