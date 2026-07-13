"""SectionRepository — CRUD for the document_section table.

Manages document sections (TOC nodes) with support for:
- Upserting sections from TocNode lists
- Retrieving sections for a document
- Marking sections as deleted (with optional effective date and basis document)
- Marking sections as modified (with optional effective date)
"""

from __future__ import annotations

from datetime import datetime

from core.models.models import TocNode
from core.observability import get_logger
from core.persistence.db_client import DatabaseClient

logger = get_logger(__name__)


class SectionRepository:
    """Repository for the document_section table."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    async def upsert_sections(
        self,
        document_id: str,
        sections: list[TocNode],
    ) -> None:
        """Upsert a list of sections for a document.

        Uses ON CONFLICT on (document_id, external_id) to update existing sections.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        if not sections:
            return

        for section in sections:
            parent_external_id = section.parent_id if section.parent_id else None
            await self._db.execute(
                """
                INSERT INTO document_section (
                    document_id, external_id, title, parent_id,
                    level, sort_order
                ) VALUES (
                    $1::uuid, $2, $3,
                    (SELECT id FROM document_section
                     WHERE document_id = $1::uuid AND external_id = $4),
                    $5, $6
                )
                ON CONFLICT (document_id, external_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        parent_id = (
                            SELECT id FROM document_section
                            WHERE document_id = $1::uuid AND external_id = $4
                        ),
                        level = EXCLUDED.level,
                        sort_order = EXCLUDED.sort_order,
                        updated_at = now()
                """,
                document_id,
                section.id,
                section.title,
                parent_external_id,
                section.level,
                getattr(section, "sort_order", 0) or 0,
            )

    async def get_sections(
        self,
        document_id: str,
    ) -> list[TocNode]:
        """Get all sections for a document, ordered by sort_order."""
        rows = await self._db.fetch(
            """
            SELECT id, external_id, title, parent_id, level, sort_order,
                   is_deleted, is_modified
            FROM document_section
            WHERE document_id = $1::uuid
            ORDER BY sort_order, level, title
            """,
            document_id,
        )
        if rows is None:
            return []

        sections: list[TocNode] = []
        for row in rows:
            parent_id = str(row["parent_id"]) if row["parent_id"] else ""
            sections.append(
                TocNode(
                    id=str(row["external_id"]),
                    document_id=document_id,
                    title=row["title"],
                    parent_id=parent_id,
                    level=row["level"],
                    child_count=0,  # Not tracked in this query
                )
            )
        return sections

    async def mark_section_deleted(
        self,
        section_id: str,
        deleted_by_document_id: str,
        effective_date: datetime | None = None,
    ) -> None:
        """Mark a section as deleted.

        Args:
            section_id: UUID of the section to mark as deleted.
            deleted_by_document_id: UUID of the document that causes the deletion.
            effective_date: Optional effective date (defaults to document's valid_from).

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        await self._db.execute(
            """
            UPDATE document_section
            SET is_deleted = true,
                deleted_by_document_id = $2::uuid,
                delete_effective_date = $3,
                updated_at = now()
            WHERE id = $1::uuid
            """,
            section_id,
            deleted_by_document_id,
            effective_date,
        )

    async def mark_section_modified(
        self,
        section_id: str,
        effective_date: datetime | None = None,
    ) -> None:
        """Mark a section as modified.

        Args:
            section_id: UUID of the section to mark as modified.
            effective_date: Optional effective date of the modification.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        await self._db.execute(
            """
            UPDATE document_section
            SET is_modified = true,
                modified_effective_date = $2,
                updated_at = now()
            WHERE id = $1::uuid
            """,
            section_id,
            effective_date,
        )


__all__ = [
    "SectionRepository",
]
