"""QdrantStore — vector storage in Qdrant with payload filtering.

Stores document chunks with embeddings and metadata payload.
Supports upsert and hybrid search with payload filters.
"""

from __future__ import annotations

import logging
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

            points.append(
                _qdrant_models.PointStruct(
                    id=chunk.id,
                    vector=chunk.embedding,
                    payload={
                        "document_id": chunk.document_id,
                        "doc_uuid": chunk.doc_uuid,
                        "text": chunk.text,
                        "section_path": chunk.section_path,
                        "section_external_ids": chunk.section_external_ids,
                        "section_uuids": chunk.section_uuids,
                        "chunk_index": chunk.chunk_index,
                    },
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

        results: list[tuple[DocumentChunk, float]] = []
        for scored in search_result.points:
            payload = scored.payload or {}
            chunk = DocumentChunk(
                id=str(scored.id),
                document_id=str(payload.get("document_id", "")),
                doc_uuid=str(payload.get("doc_uuid", "")),
                text=str(payload.get("text", "")),
                section_path=list(payload.get("section_path", [])),
                section_external_ids=list(payload.get("section_external_ids", [])),
                section_uuids=list(payload.get("section_uuids", [])),
                chunk_index=int(payload.get("chunk_index", 0)),
            )
            results.append((chunk, scored.score))

        return results

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
