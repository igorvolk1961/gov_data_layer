"""QdrantStore — vector storage in Qdrant with payload filtering.

Stores document chunks with embeddings and metadata payload.
Supports upsert and hybrid search with payload filters.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import date, datetime, timezone
from typing import Any

from core.models.models import DocumentChunk

logger = logging.getLogger(__name__)

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
                payload["not_actual_since"] = chunk.not_actual_since.isoformat()

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
        now_str = datetime.now(timezone.utc).date().isoformat()
        return _qdrant_models.Filter(
            should=[
                _qdrant_models.FieldCondition(
                    key="not_actual_since",
                    is_null=_qdrant_models.IsNullCondition(is_null=True),
                ),
                _qdrant_models.FieldCondition(
                    key="not_actual_since",
                    range=_qdrant_models.Range(gt=now_str),
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
        if isinstance(nas_raw, str):
            with contextlib.suppress(ValueError, TypeError):
                not_actual_since = date.fromisoformat(nas_raw)

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
            payload={"not_actual_since": effective_date.isoformat()},
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
    ) -> list[tuple[DocumentChunk, float]]:
        """Semantic search with payload filtering.

        Args:
            query_embedding: Query vector (float list).
            filters: Optional payload filters. Example:
                     {"document_id": "pravo-0001202012230060"}
            limit: Max number of results.

        Returns:
            List of (DocumentChunk, score) tuples, ordered by relevance.
        """
        client = await self._get_client()
        if client is None:
            logger.warning("Qdrant not available — returning empty search results")
            return []

        # Build filter condition
        qdrant_filter = None
        if filters:
            conditions = []
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
            if conditions:
                qdrant_filter = _qdrant_models.Filter(
                    must=conditions,
                )

        search_result = client.query_points(
            collection_name=self._collection,
            query=query_embedding,
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
        )

        # Merge default not_actual_since filter with caller-provided filters
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


__all__ = [
    "QdrantStore",
]
