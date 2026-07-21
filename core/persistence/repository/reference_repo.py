"""ReferenceRepository — CRUD for reference tables (document_type, organization, etc.).

All reference tables follow the same pattern:
- `id` UUID PK (auto-generated)
- `source_id` UUID FK → data_source.id
- `external_id` VARCHAR(36) — GUID string from the source API
- `name` VARCHAR(255)
- `weight` INTEGER (nullable)
- `created_at` TIMESTAMPTZ

The UNIQUE constraint is on (source_id, external_id) — the same external_id
can exist in different data sources.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.observability import get_logger
from core.persistence.db_client import DatabaseClient

if TYPE_CHECKING:
    from core.index.qdrant_store import QdrantStore
    from core.ingest.embedder import Embedder

logger = get_logger(__name__)


_VALID_REF_TABLES: frozenset[str] = frozenset(
    {
        "document_type",
        "organization",
        "jurisdiction",
        "region",
    }
)


class ReferenceRepository:
    """Repository for reference tables (document_type, organization, etc.)."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    async def get_or_create_document_type(
        self,
        source_id: str,
        external_id: str,
        name: str,
        weight: int | None = None,
    ) -> str:
        """Get or create a document_type record. Returns UUID string.

        Raises: asyncpg.PostgresError, ConnectionError
        """
        return await self._get_or_create(
            table="document_type",
            source_id=source_id,
            external_id=external_id,
            name=name,
            weight=weight,
        )

    async def get_or_create_organization(
        self,
        source_id: str,
        external_id: str,
        name: str,
        weight: int | None = None,
    ) -> str:
        """Get or create an organization record. Returns UUID string.

        Raises: asyncpg.PostgresError, ConnectionError
        """
        return await self._get_or_create(
            table="organization",
            source_id=source_id,
            external_id=external_id,
            name=name,
            weight=weight,
        )

    async def get_or_create_jurisdiction(
        self,
        source_id: str,
        code: str,
        name: str,
    ) -> str:
        """Get or create a jurisdiction record. Returns UUID string.

        Raises: asyncpg.PostgresError, ConnectionError
        """
        return await self._get_or_create(
            table="jurisdiction",
            source_id=source_id,
            external_id=code,
            name=name,
        )

    async def get_or_create_region(
        self,
        source_id: str,
        code: str,
        name: str,
    ) -> str:
        """Get or create a region record. Returns UUID string.

        Raises: asyncpg.PostgresError, ConnectionError
        """
        return await self._get_or_create(
            table="region",
            source_id=source_id,
            external_id=code,
            name=name,
        )

    async def get_or_create_topic(
        self,
        source_id: str,
        external_id: str,
        name: str,
        parent_id: str | None = None,  # noqa: ARG002 — accepted for API compat (topic table has no parent_id)
        description: str | None = None,  # noqa: ARG002 — accepted for API compat (topic table has no description)
        qdrant: QdrantStore | None = None,
        embedder: Embedder | None = None,
    ) -> tuple[str, bool]:
        """Get or create a topic record.

        Note: The ``topic`` table has no parent_id column . The ``parent_id`` and
        ``description`` parameters are accepted for API compatibility but
        ignored when inserting into the ``topic`` table.

        If the topic is newly created and ``qdrant``/``embedder`` are provided,
        the topic name is automatically embedded and stored as a vector
        in the Qdrant 'topics' collection.

        Args:
            source_id: UUID of the data source.
            external_id: External topic identifier.
            name: Topic name.
            parent_id: Ignored (topic table has no parent_id column).
            description: Ignored (topic table has no description column).
            qdrant: Optional QdrantStore for automatic vector sync.
            embedder: Optional Embedder for creating embeddings.

        Returns:
            Tuple of (topic_uuid, was_created).
            ``was_created`` is True if the topic was just inserted.

        Raises: asyncpg.PostgresError, ConnectionError
        """
        row = await self._db.fetchrow(
            """
            SELECT id FROM topic
            WHERE source_id = $1::uuid AND external_id = $2
            """,
            source_id,
            external_id,
        )
        if row is not None:
            return str(row["id"]), False

        result = await self._db.fetchrow(
            """
            INSERT INTO topic (source_id, external_id, name)
            VALUES ($1::uuid, $2, $3)
            ON CONFLICT (source_id, external_id) DO UPDATE
                SET name = EXCLUDED.name
            RETURNING id
            """,
            source_id,
            external_id,
            name,
        )
        assert result is not None
        topic_uuid = str(result["id"])

        # Auto-sync to Qdrant if a new topic was created
        if qdrant is not None and embedder is not None:
            try:
                from core.models.models import TopicPoint as _TopicPoint

                embedding = await embedder.embed([name])
                topic_point = _TopicPoint(
                    id=external_id,
                    topic_id=topic_uuid,
                    name=name,
                    embedding=embedding[0] if embedding else None,
                )
                await qdrant.upsert_topic_vectors([topic_point])
                logger.info("Synced topic '%s' to Qdrant topics collection", name)
            except Exception:
                logger.warning("Failed to sync topic '%s' to Qdrant", name, exc_info=True)

        return topic_uuid, True

    async def get_or_create_data_source(
        self,
        source_id: str,
        name: str,
        url: str,
        jurisdiction: str | None = None,
    ) -> str:
        """Get or create a data_source record. Returns UUID string.

        Raises: asyncpg.PostgresError, ConnectionError
        """
        row = await self._db.fetchrow(
            """
            SELECT id FROM data_source WHERE source_id = $1
            """,
            source_id,
        )
        if row is not None:
            return str(row["id"])

        result = await self._db.fetchrow(
            """
            INSERT INTO data_source (source_id, name, url, jurisdiction)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (source_id) DO UPDATE
                SET name = EXCLUDED.name,
                    url = EXCLUDED.url,
                    jurisdiction = COALESCE($4, data_source.jurisdiction)
            RETURNING id
            """,
            source_id,
            name,
            url,
            jurisdiction,
        )
        assert result is not None
        return str(result["id"])

    async def _get_or_create(
        self,
        table: str,
        source_id: str,
        external_id: str,
        name: str,
        weight: int | None = None,
    ) -> str:
        """Generic get-or-create for simple reference tables.

        Args:
            table: Table name (document_type, organization, jurisdiction, region).
            source_id: UUID of the data source.
            external_id: External ID from the source API.
            name: Human-readable name.
            weight: Optional sort weight.

        Returns:
            UUID string of the record.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
            ValueError: If table name is not in the allowed whitelist.
        """
        if table not in _VALID_REF_TABLES:
            msg = f"Invalid reference table: {table!r}"
            raise ValueError(msg)

        row = await self._db.fetchrow(
            f"""
            SELECT id FROM {table}
            WHERE source_id = $1::uuid AND external_id = $2
            """,
            source_id,
            external_id,
        )
        if row is not None:
            return str(row["id"])

        if weight is not None:
            result = await self._db.fetchrow(
                f"""
                INSERT INTO {table} (source_id, external_id, name, weight)
                VALUES ($1::uuid, $2, $3, $4)
                ON CONFLICT (source_id, external_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        weight = EXCLUDED.weight
                RETURNING id
                """,
                source_id,
                external_id,
                name,
                weight,
            )
        else:
            result = await self._db.fetchrow(
                f"""
                INSERT INTO {table} (source_id, external_id, name)
                VALUES ($1::uuid, $2, $3)
                ON CONFLICT (source_id, external_id) DO UPDATE
                    SET name = EXCLUDED.name
                RETURNING id
                """,
                source_id,
                external_id,
                name,
            )

        assert result is not None
        return str(result["id"])

    async def search_region_id(self, name: str) -> tuple[str, float] | None:
        """Resolve region name to region UUID via trigram search.

        Uses pg_trgm similarity search (name % $1). Returns the best match
        as (uuid, similarity_score), or None if no match found.
        The similarity score is used as a confidence signal in the response.

        Args:
            name: Region name to search for (e.g. 'Московская область').

        Returns:
            Tuple of (region_uuid, similarity_score) or None.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        row = await self._db.fetchrow(
            """
            SELECT id, similarity(name, $1) as score
            FROM region
            WHERE name % $1
            ORDER BY score DESC
            LIMIT 1
            """,
            name,
        )
        if row:
            return str(row["id"]), float(row["score"])
        return None

    async def list_regions(
        self,
        parent_id: str | None = None,
        query: str = "",
    ) -> list[dict[str, object]]:
        """List regions from the hierarchical region table.

        Args:
            parent_id: Filter by parent region ID (None = all roots).
            query: Optional search query (filters by name).

        Returns:
            List of region dicts with id, name, parent_id, description keys.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        if query:
            rows = await self._db.fetch(
                """
                SELECT id, name, parent_id, description,
                       similarity(name, $1) as score
                FROM region
                WHERE name % $1
                ORDER BY score DESC
                LIMIT 100
                """,
                query,
            )
        elif parent_id is not None:
            rows = await self._db.fetch(
                """
                SELECT id, name, parent_id, description
                FROM region
                WHERE parent_id = $1::uuid
                ORDER BY name
                """,
                parent_id,
            )
        else:
            rows = await self._db.fetch(
                """
                SELECT id, name, parent_id, description
                FROM region
                WHERE parent_id IS NULL
                ORDER BY name
                """
            )

        return [dict(r) for r in rows]


__all__ = [
    "ReferenceRepository",
]
