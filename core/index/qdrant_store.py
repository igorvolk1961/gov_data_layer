"""QdrantStore — vector storage in Qdrant with payload filtering.

Stores document chunks with embeddings and metadata payload.
Supports upsert and hybrid search with payload filters.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from core.models.models import DocumentChunk, SearchContext, TopicPoint

logger = logging.getLogger(__name__)


def _date_to_timestamp(d: date) -> float:
    """Convert a date to Unix timestamp (seconds since epoch) for Qdrant numeric comparison."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


_HAS_QDRANT = False
try:
    from qdrant_client import QdrantClient as _QdrantClient
    from qdrant_client.http import models as _qdrant_models

    _HAS_QDRANT = True
except ImportError:
    logger.warning("qdrant-client not installed — QdrantStore will use stub")


class QdrantStore:
    """Vector storage in Qdrant for document chunks.

    Each point in the collection stores:
    - id: chunk UUID (point ID)
    - vector: embedding vector
    - payload: document_id, doc_uuid, text, section_path, section_uuids, chunk_index
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection: str = "documents",
        vector_size: int = 384,
        disabled: bool = False,
    ) -> None:
        """Initialize QdrantStore.

        Args:
            host: Qdrant host.
            port: Qdrant gRPC/REST port.
            collection: Collection name.
            vector_size: Embedding vector dimension (default: 384 for sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
            disabled: If True, all operations are no-ops (for testing without Qdrant).
        """
        self._host = host
        self._port = port
        self._collection = collection
        self._vector_size = vector_size
        self._disabled = disabled
        self._client: Any = None

    async def _get_client(self) -> Any:
        """Lazy-init Qdrant client.

        Returns None if disabled (for testing without Qdrant)
        or if qdrant-client is not installed.
        """
        if self._disabled:
            return None
        if self._client is None and _HAS_QDRANT:
            self._client = _QdrantClient(host=self._host, port=self._port)
        return self._client

    async def ensure_collection(self) -> None:
        """Create collection if it doesn't exist.

        If collection exists but with a different vector_size (e.g. after
        switching embedding models), the collection is automatically deleted
        and recreated with the correct dimension.
        """
        client = await self._get_client()
        if client is None:
            logger.warning("Qdrant not available — skipping collection creation")
            return

        collections = client.get_collections().collections
        existing = {c.name for c in collections}

        if self._collection in existing:
            # Validate vector_size — recreate if dimension mismatch
            info = client.get_collection(self._collection)
            actual_size = info.config.params.vectors.size
            if actual_size != self._vector_size:
                logger.warning(
                    "Collection '%s' has vector_size=%d, expected %d — recreating",
                    self._collection,
                    actual_size,
                    self._vector_size,
                )
                client.delete_collection(self._collection)
                # Fall through to create_collection below
            else:
                logger.info("Collection '%s' already exists", self._collection)
                return

        logger.info(
            "Creating collection '%s' (vector_size=%d)", self._collection, self._vector_size
        )
        client.create_collection(
            collection_name=self._collection,
            vectors_config=_qdrant_models.VectorParams(
                size=self._vector_size,
                distance=_qdrant_models.Distance.COSINE,
            ),
        )
        # Create payload indexes for filtered search
        client.create_payload_index(
            collection_name=self._collection,
            field_name="document_id",
            field_schema=_qdrant_models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=self._collection,
            field_name="doc_uuid",
            field_schema=_qdrant_models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=self._collection,
            field_name="not_actual_since",
            field_schema=_qdrant_models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=self._collection,
            field_name="region_id",
            field_schema=_qdrant_models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=self._collection,
            field_name="topic_ids",
            field_schema=_qdrant_models.PayloadSchemaType.KEYWORD,
        )

    async def upsert_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Insert or update chunks with embeddings and payload.

        Args:
            chunks: List of DocumentChunk objects with embeddings.
        """
        if not chunks:
            return

        client = await self._get_client()
        if client is None:
            logger.warning("Qdrant not available — skipping upsert of %d chunks", len(chunks))
            return

        points: list[Any] = []
        for chunk in chunks:
            if chunk.embedding is None:
                logger.warning("Chunk %s has no embedding — skipping", chunk.id)
                continue

            payload: dict[str, Any] = {
                "document_id": chunk.document_id,
                "doc_uuid": chunk.doc_uuid,
                "text": chunk.text,
                "section_path": chunk.section_path,
                "section_external_ids": chunk.section_external_ids,
                "section_uuids": chunk.section_uuids,
                "chunk_index": chunk.chunk_index,
                "section_chunk_index": chunk.section_chunk_index,
            }
            if chunk.data_freshness is not None:
                payload["data_freshness"] = chunk.data_freshness.isoformat()
            if chunk.not_actual_since is not None:
                payload["not_actual_since"] = _date_to_timestamp(chunk.not_actual_since)
            if chunk.region is not None:
                payload["region"] = chunk.region
            if chunk.region_id is not None:
                payload["region_id"] = chunk.region_id
            if chunk.topic_ids:
                payload["topic_ids"] = chunk.topic_ids
            if chunk.topic_scores:
                payload["topic_scores"] = chunk.topic_scores

            points.append(
                _qdrant_models.PointStruct(
                    id=chunk.id,
                    vector=chunk.embedding,
                    payload=payload,
                )
            )

        if not points:
            return

        await self.ensure_collection()
        client.upsert(
            collection_name=self._collection,
            points=points,
        )
        logger.info("Upserted %d chunks to collection '%s'", len(points), self._collection)

    async def build_filter(
        self,
    ) -> _qdrant_models.Filter | None:
        """Build a payload filter for Qdrant search.

        Returns:
            Filter excluding chunks that have not_actual_since <= now(),
            or None if Qdrant models are unavailable.
        """
        if not _HAS_QDRANT:
            return None
        now_ts = _date_to_timestamp(datetime.now(timezone.utc).date())
        return _qdrant_models.Filter(
            should=[
                _qdrant_models.IsEmptyCondition(
                    is_empty=_qdrant_models.PayloadField(key="not_actual_since"),
                ),
                _qdrant_models.FieldCondition(
                    key="not_actual_since",
                    range=_qdrant_models.Range(gt=now_ts),
                ),
            ],
        )

    @staticmethod
    def _payload_to_chunk(point: Any) -> DocumentChunk:
        """Convert a Qdrant point with payload to a DocumentChunk."""
        payload = point.payload or {}
        df_raw = payload.get("data_freshness")
        data_freshness: datetime | None = None
        if isinstance(df_raw, str):
            with contextlib.suppress(ValueError, TypeError):
                data_freshness = datetime.fromisoformat(df_raw)

        nas_raw = payload.get("not_actual_since")
        not_actual_since: date | None = None
        if isinstance(nas_raw, (int, float)):
            with contextlib.suppress(ValueError, TypeError, OverflowError):
                not_actual_since = datetime.fromtimestamp(nas_raw, tz=timezone.utc).date()

        return DocumentChunk(
            id=str(point.id),
            document_id=str(payload.get("document_id", "")),
            doc_uuid=str(payload.get("doc_uuid", "")),
            text=str(payload.get("text", "")),
            section_path=list(payload.get("section_path", [])),
            section_external_ids=list(payload.get("section_external_ids", [])),
            section_uuids=list(payload.get("section_uuids", [])),
            chunk_index=int(payload.get("chunk_index", 0)),
            section_chunk_index=int(payload.get("section_chunk_index", 0)),
            data_freshness=data_freshness,
            not_actual_since=not_actual_since,
            topic_ids=list(payload.get("topic_ids", [])),
            topic_scores=dict(payload.get("topic_scores", {})),
        )

    async def deactivate_sections(
        self,
        section_uuids: list[str],
        effective_date: date,
    ) -> int:
        """Set not_actual_since on all chunks belonging to given sections.

        Scrolls Qdrant for chunks matching any of the section_uuids,
        then sets not_actual_since on their payload.

        Args:
            section_uuids: List of section UUIDs to deactivate.
            effective_date: Date from which chunks are no longer actual.

        Returns:
            Number of updated points.
        """
        client = await self._get_client()
        if client is None or not section_uuids:
            return 0

        qdrant_filter = _qdrant_models.Filter(
            should=[
                _qdrant_models.FieldCondition(
                    key="section_uuids",
                    match=_qdrant_models.MatchAny(any=section_uuids),
                ),
            ],
        )

        # Scroll all matching points
        point_ids: list[int | str] = []
        offset: int | None = None
        while True:
            result = client.scroll(
                collection_name=self._collection,
                scroll_filter=qdrant_filter,
                limit=100,
                offset=offset,
                with_payload=False,  # We only need IDs
            )
            points = result[0]
            next_offset = result[1] if len(result) > 1 else None
            for p in points:
                point_ids.append(p.id)
            if next_offset is None or next_offset == offset:
                break
            offset = next_offset

        if not point_ids:
            return 0

        # Set not_actual_since on all matching points
        client.set_payload(
            collection_name=self._collection,
            payload={"not_actual_since": _date_to_timestamp(effective_date)},
            points=point_ids,
        )
        logger.info(
            "Deactivated %d chunks (not_actual_since=%s)",
            len(point_ids),
            effective_date.isoformat(),
        )
        return len(point_ids)

    async def search(
        self,
        query_embedding: list[float],
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        context: SearchContext | None = None,
        topic_ids: list[str] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """Semantic search with payload filtering (Metadata Routing).

        Args:
            query_embedding: Query vector (float list).
            filters: Optional additional payload filters.
            limit: Max number of results.
            context: Optional SearchContext for Metadata Routing.
                     Fields region, organization, max_age_days
                     are translated to Qdrant payload filters.
            topic_ids: Optional topic UUIDs for automatic topic filtering.
                       Resolved internally from query semantics if not
                       provided through SearchContext.

        Returns:
            List of (DocumentChunk, score) tuples, ordered by relevance.
        """
        client = await self._get_client()
        if client is None:
            logger.warning("Qdrant not available — returning empty search results")
            return []

        # Build filter from explicit filters + SearchContext (Metadata Routing)
        conditions: list[Any] = []
        if filters:
            for key, value in filters.items():
                if isinstance(value, str):
                    conditions.append(
                        _qdrant_models.FieldCondition(
                            key=key,
                            match=_qdrant_models.MatchValue(value=value),
                        )
                    )
                elif isinstance(value, list):
                    conditions.append(
                        _qdrant_models.FieldCondition(
                            key=key,
                            match=_qdrant_models.MatchAny(any=value),
                        )
                    )

        # Metadata Routing: translate SearchContext to payload filters
        if context is not None:
            if context.region_id is not None:
                conditions.append(
                    _qdrant_models.FieldCondition(
                        key="region_id",
                        match=_qdrant_models.MatchValue(value=context.region_id),
                    )
                )
            if context.organization:
                conditions.append(
                    _qdrant_models.FieldCondition(
                        key="organization",
                        match=_qdrant_models.MatchAny(any=context.organization),
                    )
                )
            if context.max_age_days is not None:
                from datetime import datetime, timedelta, timezone

                cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=context.max_age_days)
                ).isoformat()
                conditions.append(
                    _qdrant_models.FieldCondition(
                        key="data_freshness",
                        range=_qdrant_models.Range(gte=cutoff),
                    )
                )

        qdrant_filter = None
        if conditions:
            qdrant_filter = _qdrant_models.Filter(
                must=conditions,
            )

        # Topic filter (auto-resolved from query or explicit)
        if topic_ids:
            conditions.append(
                _qdrant_models.FieldCondition(
                    key="topic_ids",
                    match=_qdrant_models.MatchAny(any=topic_ids),
                )
            )

        # Merge default not_actual_since filter
        default_filter = await self.build_filter()
        if default_filter is not None:
            if qdrant_filter is not None:
                qdrant_filter = _qdrant_models.Filter(
                    must=(list(qdrant_filter.must or []) + list(default_filter.must or [])),
                    should=list(default_filter.should or []),
                )
            else:
                qdrant_filter = default_filter

        search_result = client.query_points(
            collection_name=self._collection,
            query=query_embedding,
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
        )

        results: list[tuple[DocumentChunk, float]] = []
        for scored in search_result.points:
            chunk = self._payload_to_chunk(scored)
            results.append((chunk, scored.score))

        return results

    async def get_chunks_by_document_id(
        self,
        document_id: str,
    ) -> list[DocumentChunk]:
        """Retrieve all chunks for a given document by external document_id.

        Uses scroll (no vector needed) to fetch all chunks matching the
        document_id filter. Returns empty list if Qdrant is unavailable
        or no chunks found.

        Args:
            document_id: External document ID (source_id-publish_id).

        Returns:
            List of DocumentChunk objects sorted by (section_path, section_chunk_index).
        """
        client = await self._get_client()
        if client is None:
            return []

        qdrant_filter = _qdrant_models.Filter(
            must=[
                _qdrant_models.FieldCondition(
                    key="document_id",
                    match=_qdrant_models.MatchValue(value=document_id),
                ),
            ],
        )

        chunks: list[DocumentChunk] = []
        offset: int | None = None

        while True:
            result = client.scroll(
                collection_name=self._collection,
                scroll_filter=qdrant_filter,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            points = result[0]
            next_offset = result[1] if len(result) > 1 else None

            for point in points:
                chunk = self._payload_to_chunk(point)
                chunks.append(chunk)

            if next_offset is None or next_offset == offset:
                break
            offset = next_offset

        # Sort by (section_path, section_chunk_index) for deterministic order
        chunks.sort(key=lambda c: ("|".join(c.section_path), c.section_chunk_index))
        return chunks

    async def delete_document_chunks(self, document_id: str) -> None:
        """Delete all chunks for a given document.

        Args:
            document_id: External document ID (source_id-publish_id).
        """
        client = await self._get_client()
        if client is None:
            return

        client.delete(
            collection_name=self._collection,
            points_selector=_qdrant_models.FilterSelector(
                filter=_qdrant_models.Filter(
                    must=[
                        _qdrant_models.FieldCondition(
                            key="document_id",
                            match=_qdrant_models.MatchValue(value=document_id),
                        ),
                    ],
                ),
            ),
        )
        logger.info("Deleted chunks for document '%s'", document_id)

    async def count(self) -> int:
        """Get total number of chunks in the collection."""
        client = await self._get_client()
        if client is None:
            return 0
        result = client.count(collection_name=self._collection)
        return result.count  # type: ignore[no-any-return]

    async def check_health(self) -> bool:
        """Check Qdrant connectivity by listing collections.

        Returns:
            True if Qdrant is reachable and responsive, False otherwise.
        """
        client = await self._get_client()
        if client is None:
            return False
        try:
            client.get_collections()
            return True
        except Exception:
            logger.warning("Qdrant health check failed")
            return False

    # ── Topic Collection ─────────────────────────────────────────────

    async def ensure_topic_collection(self) -> None:
        """Create the 'topics' collection if it doesn't exist.

        Uses the same vector_size as the documents collection.
        """
        client = await self._get_client()
        if client is None:
            logger.warning("Qdrant not available — skipping topic collection creation")
            return

        collections = client.get_collections().collections
        existing = {c.name for c in collections}

        if "topics" in existing:
            logger.info("Topic collection already exists")
            return

        logger.info("Creating 'topics' collection (vector_size=%d)", self._vector_size)
        client.create_collection(
            collection_name="topics",
            vectors_config=_qdrant_models.VectorParams(
                size=self._vector_size,
                distance=_qdrant_models.Distance.COSINE,
            ),
        )
        # Create payload indexes for filtering
        client.create_payload_index(
            collection_name="topics",
            field_name="topic_id",
            field_schema=_qdrant_models.PayloadSchemaType.KEYWORD,
        )

    async def upsert_topic_vectors(
        self,
        topics: list[TopicPoint],
    ) -> None:
        """Upsert topic vectors into the 'topics' collection.

        Args:
            topics: List of TopicPoint objects with embeddings.
        """
        if not topics:
            return

        client = await self._get_client()
        if client is None:
            logger.warning("Qdrant not available — skipping topic upsert")
            return

        await self.ensure_topic_collection()

        points: list[Any] = []
        for topic in topics:
            if topic.embedding is None:
                logger.warning("Topic %s has no embedding — skipping", topic.id)
                continue
            payload: dict[str, Any] = {
                "topic_id": topic.topic_id,
                "name": topic.name,
                "external_id": topic.id,
            }
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, topic.id))
            points.append(
                _qdrant_models.PointStruct(
                    id=point_id,
                    vector=topic.embedding,
                    payload=payload,
                )
            )

        if not points:
            return

        client.upsert(
            collection_name="topics",
            points=points,
        )
        logger.info("Upserted %d topic vectors to 'topics' collection", len(points))

    async def delete_topic_collection(self) -> None:
        """Delete the 'topics' collection (for cleanup/reload)."""
        client = await self._get_client()
        if client is None:
            return

        collections = client.get_collections().collections
        existing = {c.name for c in collections}

        if "topics" in existing:
            client.delete_collection("topics")
            logger.info("Deleted 'topics' collection")

    async def count_topics(self) -> int:
        """Get total number of topic vectors in the topics collection."""
        client = await self._get_client()
        if client is None:
            return 0
        await self.ensure_topic_collection()
        result = client.count(collection_name="topics")
        return result.count  # type: ignore[no-any-return]

    async def search_topics(
        self,
        query_embedding: list[float],
        limit: int = 5,
        score_threshold: float = 0.2,
    ) -> list[dict[str, Any]]:
        """Search the 'topics' collection by semantic similarity.

        Args:
            query_embedding: Text embedding vector to search with.
            limit: Maximum number of results.
            score_threshold: Minimum cosine similarity score (0.0-1.0).

        Returns:
            List of dicts with keys: topic_id (external), topic_uuid, name, score.
        """
        client = await self._get_client()
        if client is None:
            return []
        await self.ensure_topic_collection()

        hits = client.query_points(
            collection_name="topics",
            query=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
        ).points

        results: list[dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                {
                    "topic_id": payload.get("topic_id", ""),
                    "topic_uuid": str(hit.id),
                    "name": payload.get("name", ""),
                    "score": hit.score,
                }
            )
        return results

    async def delete_all_collections(self) -> None:
        """Delete both 'documents' and 'topics' collections (full cleanup)."""
        client = await self._get_client()
        if client is None:
            return
        collections = client.get_collections().collections
        for c in collections:
            if c.name in ("documents", "topics"):
                client.delete_collection(c.name)
                logger.info("Deleted collection '%s'", c.name)


__all__ = [
    "QdrantStore",
]
