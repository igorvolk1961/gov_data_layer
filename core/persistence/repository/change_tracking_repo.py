"""ChangeTrackingRepository — tracks document modifications and revocations.

Manages two tables:
1. document_section_modification (M:N) — links modified sections to the
   documents that caused the modification, with optional effective_date.
2. document_revocation (1:M) — links revoking documents to revoked documents,
   with optional effective_date.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from core.observability import get_logger
from core.persistence.db_client import DatabaseClient

if TYPE_CHECKING:
    from core.analyzer.section_analyzer import SectionFact

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

    async def resolve_target_document_id(
        self,
        search_text: str | None,
    ) -> str | None:
        """Try to find a document UUID by title or document_number using trigram similarity.

        Args:
            search_text: Raw text containing a document number or name (e.g. "№ 123-ФЗ").

        Returns:
            Document UUID string if a match is found, None otherwise.
        """
        if not search_text:
            return None

        # Try exact match on document_number first
        row = await self._db.fetchval(
            """
            SELECT id FROM document
            WHERE document_number = $1
            LIMIT 1
            """,
            search_text,
        )
        if row is not None:
            return str(row)

        # Try trigram similarity search on title (requires pg_trgm extension)
        row = await self._db.fetchval(
            """
            SELECT id FROM document
            WHERE title % $1::text
            ORDER BY similarity(title, $1::text) DESC
            LIMIT 1
            """,
            search_text,
        )
        return str(row) if row is not None else None

    async def save_analysis_facts(
        self,
        facts: list[SectionFact],
        current_doc_uuid: str,
        section_uuids: dict[str, str],
    ) -> None:
        """Persist SectionFact objects to the appropriate DB tables.

        For REVOKE facts → document_revocation table.
        For MODIFY facts → document_section_modification table (if section UUIDs available).

        Args:
            facts: List of SectionFact objects from the analyzer.
            current_doc_uuid: UUID of the current document being ingested.
            section_uuids: Dict mapping section external_id → UUID.
        """
        for fact in facts:
            effective_date = (
                datetime.combine(fact.effective_date, datetime.min.time())
                if fact.effective_date
                else None
            )

            if fact.fact_type.value in ("revoke", "modify"):
                # Try to resolve the target document
                target_doc_uuid = await self.resolve_target_document_id(fact.target_document_id)

                if target_doc_uuid is None:
                    continue  # Cannot persist without a known target

                if fact.fact_type.value == "revoke":
                    await self.add_document_revocation(
                        revoking_document_id=current_doc_uuid,
                        revoked_document_id=target_doc_uuid,
                        effective_date=effective_date,
                    )
                elif fact.fact_type.value == "modify":
                    # For MODIFY, link to all sections of the current document
                    for _sec_ext_id, sec_uuid in section_uuids.items():
                        await self.add_section_modification(
                            section_id=sec_uuid,
                            modifying_document_id=target_doc_uuid,
                            effective_date=effective_date,
                        )


__all__ = [
    "ChangeTrackingRepository",
    "ModificationRecord",
    "RevocationRecord",
]
