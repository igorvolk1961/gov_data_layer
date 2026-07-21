"""DocumentRepository — CRUD for the document table.

Maps between OfficialDocument (canonical model) and the relational document table.
Handles reference table lookups (document_type, jurisdiction, region, etc.)
and M:N junction table (document_topic).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

from core.models.models import LegalStatus, OfficialDocument, Source
from core.observability import get_tracer
from core.persistence.db_client import DatabaseClient
from core.persistence.repository.reference_repo import ReferenceRepository

if TYPE_CHECKING:
    import asyncpg

_tracer: Any = None  # lazy — set via _get_tracer()


def _get_tracer() -> Any:
    """Lazy tracer accessor — avoids RuntimeError on import before configure()."""
    global _tracer
    if _tracer is None:
        try:
            _tracer = get_tracer()
        except RuntimeError:
            from adapters.base.ingest_pipeline import _NullSpan

            class _LazyTracer:
                """Minimal no-op tracer for graceful degradation."""

                def trace(self, name: str) -> _NullSpan:  # noqa: ARG002
                    return _NullSpan()

            _tracer = _LazyTracer()
    return _tracer


# ── Shared SELECT columns and JOINs ──────────────────────────────────────

_DOCUMENT_SELECT_COLUMNS = """
    d.id, d.publish_id, d.title, d.summary,
    d.document_number,
    d.valid_from, d.publish_date, d.valid_to,
    d.created_at, d.meta,
    d.document_type_id,
    d.organization_id,
    d.region_id,
    ds.source_id as source_source_id,
    ds.name as source_name,
    ds.url as source_url,
    ds.jurisdiction as source_jurisdiction,
    dt.name as doc_type_name,
    org.name as organization_name,
    j.name as jurisdiction_name,
    r.name as region_name
"""

_DOCUMENT_FROM_JOIN = """
    FROM document d
    JOIN data_source ds ON ds.id = d.source_id
    LEFT JOIN document_type dt
        ON dt.source_id = d.source_id AND dt.external_id = d.document_type_id
    LEFT JOIN organization org
        ON org.source_id = d.source_id AND org.external_id = d.organization_id
    LEFT JOIN jurisdiction j ON j.id = d.jurisdiction_id
    LEFT JOIN region r ON r.id = d.region_id
"""


class DocumentRepository:
    """Repository for the document table and related M:N junctions."""

    def __init__(
        self,
        db: DatabaseClient,
        ref_repo: ReferenceRepository,
    ) -> None:
        self._db = db
        self._ref_repo = ref_repo

    async def upsert_document(
        self,
        doc: OfficialDocument,
        source_uuid: str,
    ) -> str:
        """Insert or update a document record. Returns the document UUID.

        Args:
            doc: The canonical OfficialDocument to persist.
            source_uuid: The UUID of the data_source record.

        Returns:
            UUID string of the document record.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        # Resolve reference table IDs
        jurisdiction_id = None
        if doc.jurisdiction:
            jurisdiction_id = await self._ref_repo.get_or_create_jurisdiction(
                source_id=source_uuid,
                code=doc.jurisdiction,
                name=doc.jurisdiction,
            )

        region_id = None
        if doc.region:
            region_id = await self._ref_repo.get_or_create_region(
                source_id=source_uuid,
                code=doc.region,
                name=doc.region,
            )

        # Ensure document_type reference row exists before inserting document
        # (composite FK: document(source_id, document_type_id) → document_type(source_id, external_id))
        if doc.document_type_id:
            await self._ref_repo.get_or_create_document_type(
                source_id=source_uuid,
                external_id=doc.document_type_id,
                name=doc.document_type or doc.document_type_id,
            )

        # Ensure organization reference row exists
        if doc.organization_id:
            await self._ref_repo.get_or_create_organization(
                source_id=source_uuid,
                external_id=doc.organization_id,
                name=doc.organization or doc.organization_id,
            )

        # publish_id — сырой идентификатор документа из источника
        publish_id = doc.publish_id

        # Store document URL in meta (no dedicated url column)
        meta = dict(doc.meta) if doc.meta else {}
        meta["url"] = doc.url

        # Upsert the document
        result = await self._db.fetchrow(
            """
            INSERT INTO document (
                source_id, publish_id, title, summary,
                jurisdiction_id, region_id, document_type_id, organization_id,
                document_number,
                valid_from, publish_date, valid_to,
                created_at, meta
            ) VALUES (
                $1::uuid, $2, $3, $4,
                $5::uuid, $6::uuid, $7, $8,
                $9,
                $10, $11, $12,
                $13, $14
            )
            ON CONFLICT (source_id, publish_id) DO UPDATE
                SET title = EXCLUDED.title,
                    summary = COALESCE(EXCLUDED.summary, document.summary),
                    jurisdiction_id = COALESCE($5::uuid, document.jurisdiction_id),
                    region_id = COALESCE($6::uuid, document.region_id),
                    document_type_id = COALESCE(EXCLUDED.document_type_id, document.document_type_id),
                    organization_id = COALESCE(EXCLUDED.organization_id, document.organization_id),
                    document_number = COALESCE(EXCLUDED.document_number, document.document_number),
                    valid_from = COALESCE(EXCLUDED.valid_from, document.valid_from),
                    publish_date = COALESCE(EXCLUDED.publish_date, document.publish_date),
                    valid_to = COALESCE(EXCLUDED.valid_to, document.valid_to),
                    meta = COALESCE(EXCLUDED.meta, document.meta),
                    created_at = COALESCE($13, document.created_at),
                    updated_at = now()
            RETURNING id
            """,
            source_uuid,
            publish_id,
            doc.title,
            doc.summary,
            jurisdiction_id,
            region_id,
            doc.document_type_id,
            doc.organization_id,
            doc.document_number,
            doc.valid_from,
            doc.publish_date,
            doc.valid_to,
            doc.created_at,
            DatabaseClient.serialize_jsonb(meta),
        )

        assert result is not None
        doc_uuid = str(result["id"])

        # Upsert topics (M:N)
        if doc.topic:
            await self._upsert_document_topics(doc_uuid, source_uuid, doc.topic)

        return doc_uuid

    async def _upsert_document_topics(
        self,
        doc_uuid: str,
        source_uuid: str,
        topics: list[str],
    ) -> None:
        """Upsert M:N document_topic records."""
        for topic_name in topics:
            topic_id, _ = await self._ref_repo.get_or_create_topic(
                source_id=source_uuid,
                external_id=topic_name,
                name=topic_name,
            )
            if topic_id is not None:
                await self._db.execute(
                    """
                    INSERT INTO document_topic (document_id, topic_id)
                    VALUES ($1::uuid, $2::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    doc_uuid,
                    topic_id,
                )

    async def update_document_jurisdiction_region(
        self,
        doc_uuid: str,
        jurisdiction_id: str | None,
        region_id: str | None,
    ) -> None:
        """Update jurisdiction_id and/or region_id on a document row.

        Args:
            doc_uuid: Internal UUID of the document.
            jurisdiction_id: UUID of the jurisdiction (or None to leave unchanged).
            region_id: UUID of the region (or None to leave unchanged).

        Raises:
            ConnectionError: If not connected.
        """
        if jurisdiction_id is None and region_id is None:
            return
        await self._db.execute(
            """
            UPDATE document
            SET jurisdiction_id = COALESCE($1::uuid, jurisdiction_id),
                region_id = COALESCE($2::uuid, region_id)
            WHERE id = $3::uuid
            """,
            jurisdiction_id,
            region_id,
            doc_uuid,
        )

    async def get_document_uuid(
        self,
        publish_id: str,
    ) -> str | None:
        """Get the internal UUID of a document by its publish_id."""
        row = await self._db.fetchval(
            "SELECT id FROM document WHERE publish_id = $1",
            publish_id,
        )
        return str(row) if row else None

    async def get_document_by_publish_id(
        self,
        publish_id: str,
    ) -> OfficialDocument | None:
        """Get a document by its publish_id. Returns None if not found or on error."""
        row = await self._db.fetchrow(
            f"""
            SELECT{_DOCUMENT_SELECT_COLUMNS}
            {_DOCUMENT_FROM_JOIN}
            WHERE d.publish_id = $1
            """,
            publish_id,
        )
        if row is None:
            return None
        return await self._row_to_document(row)

    async def get_document_by_id(
        self,
        doc_uuid: str,
    ) -> OfficialDocument | None:
        """Get a document by its internal UUID. Returns None if not found or on error."""
        row = await self._db.fetchrow(
            f"""
            SELECT{_DOCUMENT_SELECT_COLUMNS}
            {_DOCUMENT_FROM_JOIN}
            WHERE d.id = $1::uuid
            """,
            doc_uuid,
        )
        if row is None:
            return None
        return await self._row_to_document(row)

    async def _row_to_document(
        self,
        row: asyncpg.Record,
    ) -> OfficialDocument | None:
        """Convert a database row to an OfficialDocument."""
        # Fetch topics for this document
        topics = await self._get_document_topics(str(row["id"]))

        meta = DatabaseClient.deserialize_jsonb(row["meta"])
        publish_id = str(row["publish_id"])
        source_id = str(row["source_source_id"])

        # DATE columns return timezone-naive date/datetime; make them UTC-aware
        def _ensure_tz(val: object) -> object:
            if isinstance(val, datetime):
                if val.tzinfo is None:
                    return val.replace(tzinfo=timezone.utc)
                return val
            if isinstance(val, date):
                return datetime(val.year, val.month, val.day, tzinfo=timezone.utc)
            return val

        # Восстанавливаем составной идентификатор документа: {source_id}-{publish_id}
        doc_id = f"{source_id}-{publish_id}"
        return OfficialDocument(
            id=doc_id,
            title=row["title"],
            source=Source(
                id=row["source_source_id"],
                name=row["source_name"],
                url=row["source_url"],
                jurisdiction=row["source_jurisdiction"],
            ),
            url=meta.get("url", row["source_url"]),
            summary=row["summary"],
            jurisdiction=row["jurisdiction_name"],
            region=row["region_name"],
            region_id=str(row["region_id"]) if row["region_id"] else None,
            topic=topics,
            organization=row["organization_name"],
            organization_id=row["organization_id"],
            document_type_id=row["document_type_id"],
            created_at=row["created_at"],
            valid_from=_ensure_tz(row["valid_from"]),
            valid_to=_ensure_tz(row["valid_to"]),
            legal_status=LegalStatus.UNKNOWN,
            document_number=row["document_number"],
            document_type=row["doc_type_name"],
            publish_id=publish_id,
            publish_date=_ensure_tz(row["publish_date"]),
            meta=meta,
        )

    async def _get_document_topics(
        self,
        doc_uuid: str,
    ) -> list[str]:
        """Get topic names for a document."""
        rows = await self._db.fetch(
            """
            SELECT t.name
            FROM document_topic dt
            JOIN topic t ON t.id = dt.topic_id
            WHERE dt.document_id = $1::uuid
            ORDER BY t.name
            """,
            doc_uuid,
        )
        if rows is None:
            return []
        return [r["name"] for r in rows]

    async def get_legal_status(
        self,
        doc_uuid: str,
    ) -> LegalStatus:
        """Determine the legal status of a document by checking revocations and modifications.

        Queries document_revocation and document_section_modification tables
        to determine if the document has been fully revoked or modified.
        Falls back to checking valid_from for ACTIVE status.

        Args:
            doc_uuid: The internal UUID of the document.

        Returns:
            LegalStatus.REVOKED if a revocation with effective_date <= now() exists.
            LegalStatus.MODIFIED if a section modification with effective_date <= now() exists.
            LegalStatus.ACTIVE if the document has valid_from in the past.
            LegalStatus.UNKNOWN otherwise.
        """
        with _get_tracer().trace("document_repo.get_legal_status") as span:
            span.set_input({"doc_uuid": doc_uuid})

            # 1. Check if document has been fully revoked
            row = await self._db.fetchval(
                """
                SELECT 1 FROM document_revocation
                WHERE revoked_document_id = $1::uuid
                  AND (effective_date IS NULL OR effective_date <= now()::date)
                LIMIT 1
                """,
                doc_uuid,
            )
            if row is not None:
                span.set_output({"status": "REVOKED"})
                return LegalStatus.REVOKED

            # 2. Check if any sections of this document have been modified
            row = await self._db.fetchval(
                """
                SELECT 1 FROM document_section_modification m
                JOIN document_section s ON s.id = m.section_id
                WHERE s.document_id = $1::uuid
                  AND (m.effective_date IS NULL OR m.effective_date <= now()::date)
                LIMIT 1
                """,
                doc_uuid,
            )
            if row is not None:
                span.set_output({"status": "MODIFIED"})
                return LegalStatus.MODIFIED

            # 3. Check if document has valid_from in the past (is in effect)
            row = await self._db.fetchval(
                """
                SELECT 1 FROM document
                WHERE id = $1::uuid
                  AND (valid_from IS NULL OR valid_from <= now())
                LIMIT 1
                """,
                doc_uuid,
            )
            if row is not None:
                span.set_output({"status": "ACTIVE"})
                return LegalStatus.ACTIVE

            span.set_output({"status": "UNKNOWN"})
            return LegalStatus.UNKNOWN

    async def search_documents(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
    ) -> list[OfficialDocument]:
        """Search documents by title (simple ILIKE search).

        This is a basic implementation. Full-text search will be added
        when Qdrant integration is implemented.
        """
        search_pattern = f"%{query}%"
        rows = await self._db.paginated_fetch(
            f"""
            SELECT{_DOCUMENT_SELECT_COLUMNS}
            {_DOCUMENT_FROM_JOIN}
            WHERE d.title ILIKE $1
            ORDER BY d.valid_from DESC
            """,
            search_pattern,
            limit=limit,
            offset=offset,
        )
        if rows is None:
            return []

        documents: list[OfficialDocument] = []
        for row in rows:
            doc = await self._row_to_document(row)
            if doc is not None:
                documents.append(doc)
        return documents


__all__ = [
    "DocumentRepository",
]
