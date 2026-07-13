"""ChangeTrackingRepository — tracks document modifications and revocations.

Manages two tables:
1. document_section_modification (M:N) — links modified sections to the
   documents that caused the modification, with optional effective_date.
2. document_revocation (1:M) — links revoking documents to revoked documents,
   with optional effective_date.
"""

from __future__ import annotations

from datetime import datetime

from core.observability import get_logger
from core.persistence.db_client import DatabaseClient

logger = get_logger(__name__)


class ModificationRecord:
    """Represents a section modification record."""

    def __init__(
        self,
        section_id: str,
        modifying_document_id: str,
        effective_date: datetime | None = None,
    ) -> None:
        self.section_id = section_id
        self.modifying_document_id = modifying_document_id
        self.effective_date = effective_date


class RevocationRecord:
    """Represents a document revocation record."""

    def __init__(
        self,
        revoking_document_id: str,
        revoked_document_id: str,
        effective_date: datetime | None = None,
    ) -> None:
        self.revoking_document_id = revoking_document_id
        self.revoked_document_id = revoked_document_id
        self.effective_date = effective_date


class ChangeTrackingRepository:
    """Repository for document modification and revocation tracking."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    async def add_section_modification(
        self,
        section_id: str,
        modifying_document_id: str,
        effective_date: datetime | None = None,
    ) -> None:
        """Record that a section was modified by a document.

        Args:
            section_id: UUID of the modified section.
            modifying_document_id: UUID of the document that caused the modification.
            effective_date: Optional effective date (defaults to document's valid_from).

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        await self._db.execute(
            """
            INSERT INTO document_section_modification
                (section_id, modifying_document_id, effective_date)
            VALUES ($1::uuid, $2::uuid, $3)
            ON CONFLICT (section_id, modifying_document_id) DO UPDATE
                SET effective_date = COALESCE($3, document_section_modification.effective_date)
            """,
            section_id,
            modifying_document_id,
            effective_date,
        )

    async def add_document_revocation(
        self,
        revoking_document_id: str,
        revoked_document_id: str,
        effective_date: datetime | None = None,
    ) -> None:
        """Record that a document revokes another document.

        Args:
            revoking_document_id: UUID of the revoking document.
            revoked_document_id: UUID of the revoked document.
            effective_date: Optional effective date (defaults to revoking document's valid_from).

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        await self._db.execute(
            """
            INSERT INTO document_revocation
                (revoking_document_id, revoked_document_id, effective_date)
            VALUES ($1::uuid, $2::uuid, $3)
            ON CONFLICT (revoking_document_id, revoked_document_id) DO UPDATE
                SET effective_date = COALESCE($3, document_revocation.effective_date)
            """,
            revoking_document_id,
            revoked_document_id,
            effective_date,
        )

    async def get_modifications_for_section(
        self,
        section_id: str,
    ) -> list[ModificationRecord]:
        """Get all modification records for a section.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        rows = await self._db.fetch(
            """
            SELECT section_id, modifying_document_id, effective_date
            FROM document_section_modification
            WHERE section_id = $1::uuid
            ORDER BY effective_date NULLS LAST
            """,
            section_id,
        )
        return [
            ModificationRecord(
                section_id=str(r["section_id"]),
                modifying_document_id=str(r["modifying_document_id"]),
                effective_date=r["effective_date"],
            )
            for r in rows
        ]

    async def get_revocations_for_document(
        self,
        document_id: str,
    ) -> list[RevocationRecord]:
        """Get all revocation records where the document is the revoker.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        rows = await self._db.fetch(
            """
            SELECT revoking_document_id, revoked_document_id, effective_date
            FROM document_revocation
            WHERE revoking_document_id = $1::uuid
            ORDER BY effective_date NULLS LAST
            """,
            document_id,
        )
        return [
            RevocationRecord(
                revoking_document_id=str(r["revoking_document_id"]),
                revoked_document_id=str(r["revoked_document_id"]),
                effective_date=r["effective_date"],
            )
            for r in rows
        ]

    async def get_revocations_by_revoked(
        self,
        document_id: str,
    ) -> list[RevocationRecord]:
        """Get all revocation records where the document is the revoked one.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        rows = await self._db.fetch(
            """
            SELECT revoking_document_id, revoked_document_id, effective_date
            FROM document_revocation
            WHERE revoked_document_id = $1::uuid
            ORDER BY effective_date NULLS LAST
            """,
            document_id,
        )
        return [
            RevocationRecord(
                revoking_document_id=str(r["revoking_document_id"]),
                revoked_document_id=str(r["revoked_document_id"]),
                effective_date=r["effective_date"],
            )
            for r in rows
        ]


__all__ = [
    "ChangeTrackingRepository",
    "ModificationRecord",
    "RevocationRecord",
]
