"""ODLService — единый core-класс, реализующий ODLServiceProtocol.

Работает через Metadata Routing: поиск напрямую через Qdrant с фильтрацией
по метаданным (region, topic). Адаптеры источников не используются —
они работают только на этапе инжеста (загрузка данных в индекс).

Поддерживает персистентность в PostgreSQL через DatabaseClient и репозитории.
Если DatabaseClient передан — персистентность обязательна, ошибки БД
пробрасываются наверх. Если не передан — персистентность не происходит,
логируется предупреждение.
"""

from __future__ import annotations

import contextlib
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from core.cache import CacheClient
from core.errors import NotFoundError
from core.index.qdrant_store import QdrantStore
from core.ingest.embedder import Embedder
from core.models.models import (
    Citation,
    ConfidenceSignals,
    DocumentChunk,
    DocumentDetail,
    LegalStatus,
    OfficialDocument,
    SearchContext,
    SearchResponse,
    SearchResult,
    SourceAvailability,
    TocNode,
)
from core.observability import get_logger, get_tracer
from core.observability.tracer import Tracer
from core.odl_service_protocol import (
    AdminQdrantStatus,
    ODLServiceProtocol,
    QdrantCollectionInfo,
    ReferenceCounts,
)
from core.persistence import DatabaseClient
from core.persistence.repository import (
    ChangeTrackingRepository,
    DocumentRepository,
    ReferenceRepository,
    SectionRepository,
)
from core.regions import RegionResolver
from core.reranker import Reranker

logger = get_logger(__name__)


class ODLService(ODLServiceProtocol):
    """Единый core-класс ODLService.

    Не зависит от SourceAdapter'ов — адаптеры используются только на этапе
    инжеста. Поиск работает через Metadata Routing: Qdrant с фильтрацией
    по region, topic, organization.

    Принимает DatabaseClient для персистентности в PostgreSQL.
    Если передан — персистентность обязательна, ошибки БД пробрасываются наверх.
    Если не передан — персистентность не происходит, логируется предупреждение.
    """

    def __init__(
        self,
        tracer: Tracer | None = None,
        cache: CacheClient | None = None,
        db: DatabaseClient | None = None,
        qdrant: QdrantStore | None = None,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._tracer: Tracer | None = tracer
        self._cache: CacheClient | None = cache
        self._db: DatabaseClient | None = db
        self._qdrant: QdrantStore | None = qdrant
        self._embedder: Embedder | None = embedder
        self._reranker: Reranker | None = reranker
        self._doc_repo: DocumentRepository | None = None
        self._ref_repo: ReferenceRepository | None = None
        self._section_repo: SectionRepository | None = None
        self._change_repo: ChangeTrackingRepository | None = None

    @property
    def tracer(self) -> Tracer:
        """Lazy tracer — defers get_tracer() until first use.

        This avoids RuntimeError at import time when the tracer hasn't been
        configured yet (e.g. during test collection).
        """
        if self._tracer is None:
            self._tracer = get_tracer()
        return self._tracer

    @property
    def _doc_repo_lazy(self) -> DocumentRepository | None:
        """Lazy init of DocumentRepository (only if DB is available)."""
        if self._doc_repo is None and self._db is not None:
            ref_repo = self._ref_repo_lazy
            assert ref_repo is not None
            self._doc_repo = DocumentRepository(self._db, ref_repo)
        return self._doc_repo

    @property
    def _ref_repo_lazy(self) -> ReferenceRepository | None:
        """Lazy init of ReferenceRepository (only if DB is available)."""
        if self._ref_repo is None and self._db is not None:
            self._ref_repo = ReferenceRepository(self._db)
        return self._ref_repo

    @property
    def _section_repo_lazy(self) -> SectionRepository | None:
        """Lazy init of SectionRepository (only if DB is available)."""
        if self._section_repo is None and self._db is not None:
            self._section_repo = SectionRepository(self._db)
        return self._section_repo

    @property
    def _change_repo_lazy(self) -> ChangeTrackingRepository | None:
        """Lazy init of ChangeTrackingRepository (only if DB is available)."""
        if self._change_repo is None and self._db is not None:
            self._change_repo = ChangeTrackingRepository(self._db)
        return self._change_repo

    @property
    def _embedder_lazy(self) -> Embedder:
        """Lazy init of Embedder."""
        if self._embedder is None:
            self._embedder = Embedder()
        return self._embedder

    @property
    def _reranker_lazy(self) -> Reranker:
        """Lazy init of Reranker — falls back to TopicAwareReranker from config."""
        if self._reranker is None:
            from core.api.app_config import get_config
            from core.reranker import PassThroughReranker, TopicAwareReranker

            cfg = get_config().reranker
            if cfg.provider == "passthrough":
                self._reranker = PassThroughReranker()
            else:
                self._reranker = TopicAwareReranker(
                    w_vector=cfg.w_vector,
                    w_topic=cfg.w_topic,
                )
        return self._reranker

    @property
    def _qdrant_lazy(self) -> QdrantStore | None:
        """Lazy access to QdrantStore."""
        return self._qdrant

    @property
    def _region_resolver(self) -> RegionResolver | None:
        """Lazy init of RegionResolver."""
        if self._ref_repo_lazy is not None:
            return RegionResolver(
                ref_repo=self._ref_repo_lazy,
                cache=self._cache,
            )
        return None

    @staticmethod
    def _cache_key(method: str, *args: str) -> str:
        """Build a deterministic cache key from method name and arguments.

        Uses SHA-256 to produce a fixed-length, collision-resistant key.

        Args:
            method: The method name (e.g. 'search', 'detail', 'topics', 'toc').
            *args: String representations of all arguments.

        Returns:
            A cache key like 'odl:search:abc123...'.
        """
        raw = "|".join([method, *args])
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return f"odl:{method}:{digest}"

    async def _persist_document(
        self,
        doc: OfficialDocument,
        source_id: str,
        toc: list[TocNode] | None = None,
    ) -> None:
        """Persist a canonical document + its sections to PostgreSQL.

        If DatabaseClient is not configured (self._db is None), records a
        tracer span and returns. If configured, persistence is mandatory —
        errors propagate to the caller.

        This is called as a side-effect from get_document_detail(), so the
        try/except in that method will catch and log any DB errors without
        failing the API response.
        """
        if self._db is None:
            with self.tracer.trace("persistence.skip_no_db") as span:
                span.set_input({"document_id": doc.id, "source_id": source_id})
            return

        # Ensure DB connection is established
        await self._db.connect()

        ref_repo = self._ref_repo_lazy
        doc_repo = self._doc_repo_lazy
        section_repo = self._section_repo_lazy

        # Narrow types: all repos are guaranteed non-None when _db is not None
        assert ref_repo is not None
        assert doc_repo is not None
        assert section_repo is not None

        # 1. Get or create data source
        source_uuid = await ref_repo.get_or_create_data_source(
            source_id=source_id,
            name=doc.source.name,
            url=doc.url,
        )

        # 2. Upsert the document
        doc_uuid = await doc_repo.upsert_document(doc, source_uuid)

        # 3. Upsert sections (TOC) — mapping returned for tracing
        if toc:
            section_map = await section_repo.upsert_sections(doc_uuid, toc)
            with self.tracer.trace("persistence.sections_upserted") as span:
                span.set_output({"count": len(section_map)})

    async def search_documents(
        self,
        query: str,
        context: SearchContext | None = None,
        parent_span: Any = None,
    ) -> SearchResponse:
        """Поиск документов через Qdrant с обогащением из PostgreSQL.

        Векторный поиск по Qdrant → обогащение метаданных документа
        (url, source_name, title) из реляционной БД.
        Если БД недоступна — возвращаются только данные из Qdrant.

        Результаты кэшируются в Redis на 5 минут (cache-aside).
        При недоступности Redis запрос проходит напрямую в Qdrant.

        Args:
            query: Текст поискового запроса.
            context: Опциональные параметры фильтрации.
            parent_span: Родительский span для иерархии трейсов.
                        Если передан — поиск создаёт дочерние span'ы.
                        Если None — создаётся корневой trace.

        Returns:
            SearchResponse с результатами поиска.
        """
        ctx = context or SearchContext()
        offset = ctx.offset
        max_results = ctx.max_results

        # --- Cache-aside: check cache first ---
        cache_key = self._cache_key("search", query, ctx.model_dump_json())
        if self._cache is not None:
            try:
                cached = await self._cache.get(cache_key)
                if cached is not None:
                    return SearchResponse.model_validate_json(cached)
            except Exception:
                # Cache error — just log via tracer below
                pass

        results: list[SearchResult] = []

        # Determine the root span for this search operation
        search_span: Any = parent_span
        ctx_mgr: Any = contextlib.nullcontext()
        if parent_span is None:
            search_span = self.tracer.trace("search_documents", query=query[:100])
            ctx_mgr = search_span

        def _child(name: str, **tags: str) -> Any:
            return self.tracer.span(name, parent=search_span, **tags)

        with ctx_mgr:
            search_span.set_input(ctx.model_dump(mode="json"))

            if self._qdrant is None:
                search_span.set_output({"total_count": 0, "reason": "qdrant_not_configured"})
                return SearchResponse(results=[], total_count=0, offset=offset)

            # Resolve region text to region_id for Qdrant filtering
            if ctx.region is not None and ctx.region_id is None:
                resolver = self._region_resolver
                if resolver is not None:
                    region_result = await resolver.resolve(ctx.region)
                    if region_result is not None:
                        ctx.region_id, ctx.region_confidence = region_result

            # Check if region context is missing (regional docs exist but no region specified)
            missing_context, suggested_clarification = await self._check_missing_region(ctx, query)

            try:
                embedder = self._embedder_lazy
                query_vector = await embedder.embed_query(query)

                # Determine relevant topics by semantic similarity to query
                _topic_filter: list[str] | None = None
                try:
                    _query_topic_matches = await self._qdrant.search_topics(
                        query_embedding=query_vector,
                        limit=3,
                        score_threshold=0.3,
                    )
                    if _query_topic_matches:
                        _topic_filter = [m["topic_id"] for m in _query_topic_matches]
                except Exception:
                    pass  # graceful degradation — no topic filtering

                qspan = _child("search.qdrant")
                with qspan:
                    qdrant_chunks = await self._qdrant.search(
                        query_embedding=query_vector,
                        limit=max_results + offset,
                        context=ctx,
                        topic_ids=_topic_filter,
                        parent_span=qspan,
                    )
                    qspan.set_output({"hits": len(qdrant_chunks)})

                # Re-rank ALL fetched chunks using pluggable Reranker (before pagination)
                reranker = self._reranker_lazy
                rspan = _child("search.rerank")
                with rspan:
                    all_chunks = await reranker.rerank(
                        query=query,
                        query_embedding=query_vector,
                        chunks=qdrant_chunks,
                        topic_matches=_query_topic_matches,
                    )
                    rspan.set_output({"reranked": len(all_chunks)})

                # Page chunks for current page (after ranking)
                page_chunks = list(all_chunks[offset : offset + max_results])

                # Resolve topic_id (UUID) → topic name from DB (one query for all chunks)
                _all_topic_ids: set[str] = set()
                for _ch, _ in page_chunks:
                    for _tid in _ch.topic_ids:
                        if _tid:
                            _all_topic_ids.add(_tid)
                _topic_id_to_name: dict[str, str] = {}
                if _all_topic_ids and self._db is not None:
                    try:
                        _rows = await self._db.fetch(
                            "SELECT id, name FROM topic WHERE id = ANY($1::uuid[])",
                            list(_all_topic_ids),
                        )
                        for _r in _rows:
                            _topic_id_to_name[str(_r["id"])] = str(_r["name"])
                    except Exception:
                        pass  # graceful degradation — topics stay empty

                # Группируем чанки по document_id — один результат = один документ
                # Для каждого документа храним (лучший score, лучший snippet, все section_path)
                doc_buckets: dict[str, list[tuple[DocumentChunk, float]]] = {}
                for chunk, score in page_chunks:
                    doc_buckets.setdefault(chunk.document_id, []).append((chunk, score))

                # Обогащение из PostgreSQL
                doc_repo = self._doc_repo_lazy

                for doc_id, chunk_list in doc_buckets.items():
                    # Best chunk: highest score
                    best_chunk, best_score = max(chunk_list, key=lambda x: x[1])

                    # Score threshold — политика агента (механизм/политика)
                    if ctx.score_threshold is not None and best_score < ctx.score_threshold:
                        continue

                    # Данные из чанка (Qdrant payload) — приоритет для region и topic
                    region = best_chunk.region

                    # Строим title из метаданных документа
                    url = ""
                    source_name = ""
                    jurisdiction: str | None = None
                    topic_list: list[str] = []
                    organization_list: list[str] = []
                    document_number: str | None = None
                    document_type: str | None = None
                    legal_status_val = LegalStatus.UNKNOWN
                    data_freshness = best_chunk.data_freshness
                    doc_title = ""  # будет заполнен из doc_meta.title

                    if doc_repo is not None:
                        pspan = _child("search.pg_lookup")
                        with pspan:
                            try:
                                publish_id = doc_id.split("-", 1)[1] if "-" in doc_id else doc_id
                                doc_meta = await doc_repo.get_document_by_publish_id(publish_id)
                                if doc_meta is not None:
                                    # Clean HTML from title
                                    raw_title = doc_meta.title or ""
                                    for tag in ["<br/>", "<br />", "<br>", "</br>"]:
                                        raw_title = raw_title.replace(tag, " ")
                                    doc_title = " ".join(raw_title.split())
                                    url = doc_meta.url or ""
                                    source_name = doc_meta.source.name if doc_meta.source else ""
                                    jurisdiction = doc_meta.jurisdiction
                                    # region и topic берём из чанка, не из БД
                                    organization_list = (
                                        [doc_meta.organization] if doc_meta.organization else []
                                    )
                                    document_number = doc_meta.document_number
                                    document_type = doc_meta.document_type
                                    legal_status_val = doc_meta.legal_status
                                    data_freshness = doc_meta.valid_from or doc_meta.created_at
                                    pspan.set_output({"found": True, "source": source_name})
                                else:
                                    pspan.set_output({"found": False})
                            except Exception as exc:
                                pspan.set_error(exc)
                                pspan.set_output({"found": False})

                    # Если title не найден — используем заголовок из чанка
                    if not doc_title:
                        doc_title = best_chunk.text[:120] + (
                            "…" if len(best_chunk.text) > 120 else ""
                        )

                    # Resolve topic_id → topic names for the best chunk
                    topic_list = [
                        _topic_id_to_name[tid]
                        for tid in best_chunk.topic_ids
                        if tid in _topic_id_to_name
                    ]

                    # Сниппет — текст лучшего чанка
                    snippet = best_chunk.text[:300] + ("…" if len(best_chunk.text) > 300 else "")

                    result = SearchResult(
                        id=doc_id,
                        title=doc_title,
                        snippet=snippet,
                        url=url,
                        source_name=source_name,
                        jurisdiction=jurisdiction,
                        region=region,
                        topic=topic_list,
                        organization=organization_list,
                        created_at=datetime.now(timezone.utc),
                        legal_status=legal_status_val,
                        document_number=document_number,
                        document_type=document_type,
                        confidence=ConfidenceSignals(
                            retrieval_relevance=best_score,
                            data_freshness=data_freshness,
                            source_availability=SourceAvailability.AVAILABLE,
                        ),
                    )
                    results.append(result)

            except Exception as exc:
                espan = _child("search.qdrant_error")
                with espan:
                    espan.set_error(exc)
                    espan.set_output({"error": str(exc)[:200]})

            response = SearchResponse(
                results=results,
                total_count=len(results),  # уникальные документы (1 документ = 1 результат)
                offset=offset,
                missing_context=missing_context,
                suggested_clarification_prompt=suggested_clarification,
            )

            # --- Cache-aside: populate cache after successful search ---
            if self._cache is not None:
                try:
                    await self._cache.set(
                        cache_key,
                        response.model_dump_json(),
                        ttl=timedelta(minutes=5),
                    )
                except Exception:
                    # Cache write error — non-critical, just note via tracer
                    err_span = _child("search.cache_write_error")
                    with err_span:
                        err_span.set_output({"error": "failed to cache search result"})

            search_span.set_output({"total_count": response.total_count})
            return response

    async def get_document_detail(
        self,
        source_id: str,
        query: str | None = None,
        context: SearchContext | None = None,
        max_citation_length: int = 2000,
    ) -> DocumentDetail:
        """Полная карточка документа — сборка из Qdrant + PostgreSQL.

        Принимает ID документа в том же формате, что возвращает search:
        - `{source_id}-{publish_id}` (например `pravo-0001202012230060`)
        - или просто `publish_id` (например `0001202012230060`)

        1. Извлекает publish_id из составного ID.
        2. Получает метаданные документа из PostgreSQL (через doc_repo).
        3. Если передан query — ищет релевантные чанки в Qdrant.
        4. Получает TOC из PostgreSQL (через section_repo).
        5. Собирает цитаты из чанков, обрезает до max_citation_length.
        6. Если БД недоступна — NotFoundError.

        Результаты кэшируются в Redis на 1 час (cache-aside).
        """
        # --- Cache-aside: check cache first ---
        cache_key = self._cache_key("detail", source_id)
        if self._cache is not None:
            try:
                cached = await self._cache.get(cache_key)
                if cached is not None:
                    return DocumentDetail.model_validate_json(cached)
            except Exception:
                logger.warning("Cache lookup failed for detail — falling through", exc_info=True)

        with self.tracer.trace("get_document_detail", source_id=source_id) as span:
            span.set_input(
                {"source_id": source_id, "query": query, "max_citation_length": max_citation_length}
            )

            # Get document metadata from PostgreSQL
            doc_repo = self._doc_repo_lazy
            if doc_repo is None:
                raise NotFoundError(f"Document {source_id} not found (no database configured)")

            # Разбираем составной ID: search возвращает "source_id-publish_id"
            publish_id = source_id.split("-", 1)[1] if "-" in source_id else source_id

            doc_meta = await doc_repo.get_document_by_publish_id(publish_id)
            if doc_meta is None:
                raise NotFoundError(f"Document {publish_id} not found")

            # Get TOC from PostgreSQL
            # Note: doc_meta.id is in compound format "source_id-publish_id",
            # but section_repo.get_sections expects the DB UUID. Fetch it.
            section_repo = self._section_repo_lazy
            toc: list[TocNode] = []
            if section_repo is not None:
                try:
                    db_uuid = await doc_repo.get_document_uuid(publish_id)
                    if db_uuid:
                        toc = await section_repo.get_sections(db_uuid)
                except Exception:
                    logger.exception("Failed to get TOC for document %s", source_id)

            # Build citations from Qdrant chunks
            # Qdrant chunks хранят document_id в формате "source_id-publish_id"
            qdrant_doc_id = f"{doc_meta.source.id}-{publish_id}" if doc_meta.source else publish_id

            citations = await self._build_citations_from_qdrant(
                doc_id=qdrant_doc_id,
                doc_url=doc_meta.url or "",
                doc_title=doc_meta.title or "",
                toc=toc,
                query=query,
                context=context,
                max_citation_length=max_citation_length,
            )

            detail = DocumentDetail(
                id=doc_meta.id,
                title=doc_meta.title or "",
                url=doc_meta.url or "",
                source_name=doc_meta.source.name if doc_meta.source else "",
                jurisdiction=doc_meta.jurisdiction,
                region=doc_meta.region,
                topic=doc_meta.topic,
                organization=[doc_meta.organization] if doc_meta.organization else [],
                created_at=doc_meta.created_at,
                valid_from=doc_meta.valid_from,
                valid_to=doc_meta.valid_to,
                legal_status=doc_meta.legal_status,
                citations=citations,
                toc=toc,
            )
            span.set_output({"document_id": detail.id, "title": detail.title})

            # --- Cache-aside: populate cache after successful lookup ---
            if self._cache is not None:
                try:
                    await self._cache.set(
                        cache_key,
                        detail.model_dump_json(),
                        ttl=timedelta(hours=1),
                    )
                except Exception:
                    logger.warning("Failed to cache document detail", exc_info=True)

        return detail

    async def _build_citations_from_qdrant(
        self,
        doc_id: str,
        doc_url: str,
        doc_title: str,
        toc: list[TocNode],
        query: str | None = None,
        context: SearchContext | None = None,
        max_citation_length: int = 2000,
    ) -> list[Citation]:
        """Build citations from Qdrant chunks, falling back to title if unavailable.

        Если передан query — ищет релевантные чанки через векторный поиск
        по Qdrant (ограниченные document_id) и возвращает только цитаты
        из релевантных разделов. Если query не передан — возвращает все
        разделы документа.

        Args:
            doc_id: ID документа в Qdrant (source_id-publish_id).
            doc_url: URL документа.
            doc_title: Заголовок документа.
            toc: Оглавление документа.
            query: Поисковый запрос для фильтрации citations.
            context: Контекст с параметрами фильтрации (score_threshold и др.).
            max_citation_length: Максимальная суммарная длина всех цитат.

        Returns:
            Список Citation, отсортированный по релевантности.
        """
        qdrant = self._qdrant_lazy
        if qdrant is not None:
            try:
                if query:
                    # Векторный поиск по чанкам документа
                    ctx = context or SearchContext()
                    embedder = self._embedder_lazy
                    query_vector = await embedder.embed_query(query)
                    score_threshold = (
                        ctx.score_threshold if ctx.score_threshold is not None else 0.5
                    )
                    max_chunks = ctx.max_results  # default 5

                    qdrant_chunks = await qdrant.search(
                        query_embedding=query_vector,
                        limit=max_chunks,
                        context=ctx,
                        filters={"document_id": doc_id},
                    )
                    # Filter by score threshold, sort descending, take top N
                    filtered = [
                        (chunk, score) for chunk, score in qdrant_chunks if score >= score_threshold
                    ]
                    if filtered:
                        filtered.sort(key=lambda x: x[1], reverse=True)
                        # Take only top max_chunks
                        top_chunks = [chunk for chunk, _ in filtered[:max_chunks]]
                        citations = self._merge_chunks_to_citations(top_chunks, doc_id, doc_url)
                        # Truncate to max_citation_length
                        return self._truncate_citations(citations, max_citation_length)
                else:
                    # Нет query — возвращаем все чанки документа
                    chunks = await qdrant.get_chunks_by_document_id(doc_id)
                    if chunks:
                        return self._merge_chunks_to_citations(chunks, doc_id, doc_url)
            except Exception as exc:
                logger.warning("Qdrant error building citations for %s: %s", doc_id, exc)

        # Fallback: one citation from title
        return [
            Citation(
                text=doc_title or doc_id,
                source_id=doc_id,
                url=doc_url or "",
                section=[toc[0].title] if toc else None,
            ),
        ]

    @staticmethod
    def _truncate_citations(
        citations: list[Citation],
        max_length: int,
    ) -> list[Citation]:
        """Truncate citations list to fit within max_length total characters.

        Если суммарная длина всех citation.text превышает max_length,
        менее релевантные (последние в списке) цитаты отбрасываются.
        """
        total = 0
        result: list[Citation] = []
        for c in citations:
            if total + len(c.text) > max_length:
                # Частичное усечение последней цитаты
                remaining = max_length - total
                if remaining > 100:
                    result.append(
                        Citation(
                            text=c.text[:remaining] + "…",
                            source_id=c.source_id,
                            url=c.url,
                            section=c.section,
                        )
                    )
                break
            result.append(c)
            total += len(c.text)
        return result

    @staticmethod
    def _merge_chunks_to_citations(
        chunks: list[DocumentChunk],
        doc_id: str,
        doc_url: str,
    ) -> list[Citation]:
        """Merge chunks grouped by section_path into one Citation per section."""
        citations: list[Citation] = []

        grouped: dict[str, list[DocumentChunk]] = {}
        group_order: list[str] = []
        for chunk in chunks:
            key = "|".join(chunk.section_path)
            if key not in grouped:
                grouped[key] = []
                group_order.append(key)
            grouped[key].append(chunk)

        for key in group_order:
            group = grouped[key]
            merged = ODLService._merge_overlapping_chunks(group)
            section = group[0].section_path if group[0].section_path else None

            citations.append(
                Citation(
                    text=merged,
                    source_id=doc_id,
                    url=doc_url,
                    section=section,
                )
            )

        return citations

    @staticmethod
    def _merge_overlapping_chunks(chunks: list[DocumentChunk]) -> str:
        """Merge chunk texts with overlap trimming.

        Chunks are ordered by section_chunk_index (ascending).
        For each consecutive pair, if the end of the previous chunk
        overlaps with the start of the next chunk (≥50 chars match),
        the overlapping portion is removed from the next chunk.

        If no overlap is detected, chunks are joined with a space.
        """
        if not chunks:
            return ""
        if len(chunks) == 1:
            return chunks[0].text

        result = chunks[0].text
        for i in range(1, len(chunks)):
            prev = result
            curr = chunks[i].text

            # Find maximum overlap between end of prev and start of curr
            overlap_len = 0
            min_overlap = 50  # minimum chars to consider as intentional overlap
            max_check = min(len(prev), len(curr), 500)  # don't check beyond 500 chars

            for n in range(max_check, min_overlap - 1, -1):
                if prev[-n:] == curr[:n]:
                    overlap_len = n
                    break

            if overlap_len >= min_overlap:
                result = prev + curr[overlap_len:]
            else:
                # No significant overlap — join with separator
                result = prev + ("\n\n" if prev and curr else "") + curr

        return result

    async def _check_missing_region(
        self,
        ctx: SearchContext,
        _query: str = "",
    ) -> tuple[str | None, str | None]:
        """Check if region context is missing when regional docs exist.

        If the query has no region specified but the search context includes
        topic/rubric filters, checks PostgreSQL for jurisdiction distribution
        of documents under those rubrics. If regional documents exist,
        suggests the agent ask for the user's region.

        Returns:
            Tuple of (missing_context_type, suggested_clarification_prompt).
            Both None if region is already specified or no rubric context.
        """
        if ctx.region is not None:
            return None, None
        ref_repo = self._ref_repo_lazy
        if ref_repo is None:
            return None, None
        try:
            # Stub: simplified check — actual implementation would query
            # document_jurisdiction distribution for the requested rubrics
            _ = ref_repo  # placeholder
            return None, None
        except Exception:
            logger.exception("Failed to check missing region")
            return None, None

    # ── Admin / Verification Methods ──────────────────────────────────

    async def admin_get_reference_counts(self) -> ReferenceCounts:
        """Get counts of all reference tables for verification."""
        counts = ReferenceCounts()
        if self._db is None:
            return counts

        try:
            await self._db.connect()
            tables = [
                ("region", "region"),
                ("organization", "organization"),
                ("document_type", "document_type"),
                ("topic", "topic"),
                ("document", "document"),
                ("document_section", "document_section"),
                ("section_topic", "section_topic"),
            ]
            for attr, table in tables:
                row = await self._db.fetchval(f"SELECT COUNT(*) FROM {table}")
                setattr(counts, attr, row or 0)
        except Exception:
            logger.exception("Failed to get reference counts")
        return counts

    async def admin_get_qdrant_status(self) -> AdminQdrantStatus:
        """Get Qdrant collections status for verification."""
        status = AdminQdrantStatus()
        if self._qdrant is None:
            return status

        try:
            doc_count = await self._qdrant.count()
            status.documents = QdrantCollectionInfo(exists=True, count=doc_count)
        except Exception:
            logger.warning("Failed to count documents collection")

        try:
            topic_count = await self._qdrant.count_topics()
            status.topics = QdrantCollectionInfo(exists=True, count=topic_count)
        except Exception:
            logger.warning("Failed to count topics collection")

        return status


__all__ = [
    "ODLService",
]
