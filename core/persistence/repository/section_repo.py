"""SectionRepository — CRUD for the document_section table.

Manages document sections (TOC nodes) with support for:
- Upserting sections from TocNode lists
- Retrieving sections for a document
- Marking sections as deleted (with optional effective date and basis document)
- Marking sections as modified (with optional effective date)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.models.models import TocNode
from core.observability import get_tracer
from core.persistence.db_client import DatabaseClient

_tracer_section: Any = None  # lazy — set via _get_tracer()


def _get_tracer() -> Any:
    """Lazy tracer accessor — avoids RuntimeError on import before configure()."""
    global _tracer_section
    if _tracer_section is None:
        try:
            _tracer_section = get_tracer()
        except RuntimeError:
            from adapters.base.ingest_pipeline import _NullSpan

            class _LazyTracer:
                """Minimal no-op tracer for graceful degradation."""

                def trace(self, name: str) -> _NullSpan:  # noqa: ARG002
                    return _NullSpan()

            _tracer_section = _LazyTracer()
    return _tracer_section


class SectionRepository:
    """Repository for the document_section table."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    async def upsert_sections(
        self,
        document_id: str,
        sections: list[TocNode],
    ) -> dict[str, str]:
        """Upsert a list of sections for a document.

        For each section, checks by (document_id, external_id) whether a record
        already exists. If it does — updates it; otherwise inserts a new row.

        Returns:
            Dict mapping external_id -> PostgreSQL UUID for each upserted section.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        if not sections:
            return {}

        section_map: dict[str, str] = {}
        for section in sections:
            parent_external_id = section.parent_id if section.parent_id else None
            sort_order = getattr(section, "sort_order", 0) or 0

            # Check if a section with this (document_id, external_id) already exists
            existing = await self._db.fetchval(
                """
                SELECT id FROM document_section
                WHERE document_id = $1::uuid AND external_id = $2
                """,
                document_id,
                section.id,
            )

            if existing is not None:
                # Update existing row
                row = await self._db.fetchval(
                    """
                    UPDATE document_section
                    SET title = $3,
                        parent_id = (
                            SELECT id FROM document_section
                            WHERE document_id = $1::uuid AND external_id = $4
                        ),
                        level = $5,
                        ordinal = $6,
                        updated_at = now()
                    WHERE id = $2::uuid
                    RETURNING id
                    """,
                    document_id,
                    existing,
                    section.title,
                    parent_external_id,
                    section.level,
                    sort_order,
                )
            else:
                # Insert new row
                row = await self._db.fetchval(
                    """
                    INSERT INTO document_section (
                        document_id, external_id, title, parent_id,
                        level, ordinal
                    ) VALUES (
                        $1::uuid, $2, $3,
                        (SELECT id FROM document_section
                         WHERE document_id = $1::uuid AND external_id = $4),
                        $5, $6
                    )
                    RETURNING id
                    """,
                    document_id,
                    section.id,
                    section.title,
                    parent_external_id,
                    section.level,
                    sort_order,
                )
            if row is not None:
                section_map[section.id] = str(row)
        return section_map

    async def get_sections(
        self,
        document_id: str,
    ) -> list[TocNode]:
        """Get all sections for a document, ordered by ordinal."""
        rows = await self._db.fetch(
            """
            SELECT id, external_id, title, parent_id, level, ordinal,
                   is_deleted, is_modified
            FROM document_section
            WHERE document_id = $1::uuid
            ORDER BY ordinal, level, title
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

    async def is_section_actual(
        self,
        section_uuid: str,
    ) -> bool:
        """Check whether a section is still actual.

        A section is non-actual if any of these conditions hold:
        1. The parent document has been revoked (document_revocation)
        2. The section has been deleted (is_deleted = true)
        3. The section has been modified (is_modified = true)
        4. There is an external modification record (document_section_modification)

        Args:
            section_uuid: UUID of the section to check.

        Returns:
            True if the section is still actual, False otherwise.
        """
        with _get_tracer().trace("section_repo.is_section_actual") as span:
            span.set_input({"section_uuid": section_uuid})

            # 1. Check if parent document has been revoked
            row = await self._db.fetchval(
                """
                SELECT 1 FROM document_section s
                JOIN document_revocation r ON r.revoked_document_id = s.document_id
                WHERE s.id = $1::uuid
                  AND (r.effective_date IS NULL OR r.effective_date <= now()::date)
                LIMIT 1
                """,
                section_uuid,
            )
            if row is not None:
                span.set_output({"actual": False})
                return False

            # 2. Check if section was marked as deleted
            row = await self._db.fetchval(
                """
                SELECT 1 FROM document_section
                WHERE id = $1::uuid
                  AND is_deleted = true
                  AND (delete_effective_date IS NULL OR delete_effective_date <= now()::date)
                LIMIT 1
                """,
                section_uuid,
            )
            if row is not None:
                span.set_output({"actual": False})
                return False

            # 3. Check if section was directly marked as modified
            row = await self._db.fetchval(
                """
                SELECT 1 FROM document_section
                WHERE id = $1::uuid
                  AND is_modified = true
                  AND (modified_effective_date IS NULL OR modified_effective_date <= now()::date)
                LIMIT 1
                """,
                section_uuid,
            )
            if row is not None:
                span.set_output({"actual": False})
                return False

            # 4. Check document_section_modification table for external changes
            row = await self._db.fetchval(
                """
                SELECT 1 FROM document_section_modification
                WHERE section_id = $1::uuid
                  AND (effective_date IS NULL OR effective_date <= now()::date)
                LIMIT 1
                """,
                section_uuid,
            )
            if row is not None:
                span.set_output({"actual": False})
                return False

            span.set_output({"actual": True})
            return True


__all__ = [
    "SectionRepository",
]
