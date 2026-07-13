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

from core.observability import get_logger
from core.persistence.db_client import DatabaseClient

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
        parent_id: str | None = None,
        description: str | None = None,
    ) -> str:
        """Get or create a topic record. Returns UUID string.

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
            return str(row["id"])

        result = await self._db.fetchrow(
            """
            INSERT INTO topic (source_id, external_id, name, parent_id, description)
            VALUES ($1::uuid, $2, $3, $4::uuid, $5)
            ON CONFLICT (source_id, external_id) DO UPDATE
                SET name = EXCLUDED.name,
                    parent_id = COALESCE($4::uuid, topic.parent_id),
                    description = COALESCE($5, topic.description)
            RETURNING id
            """,
            source_id,
            external_id,
            name,
            parent_id,
            description,
        )
        assert result is not None
        return str(result["id"])

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


__all__ = [
    "ReferenceRepository",
]
