"""DocumentRepository — CRUD for the document table.

Maps between OfficialDocument (canonical model) and the relational document table.
Handles reference table lookups (document_type, jurisdiction, region, etc.)
and M:N junction tables (document_organization, document_topic).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from core.models.models import LegalStatus, OfficialDocument, Source
from core.observability import get_logger
from core.persistence.db_client import DatabaseClient
from core.persistence.repository.reference_repo import ReferenceRepository

if TYPE_CHECKING:
    import asyncpg

logger = get_logger(__name__)


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
        doc_type_id = None
        if doc.document_type:
            doc_type_id = await self._ref_repo.get_or_create_document_type(
                source_id=source_uuid,
                external_id=doc.document_type,
                name=doc.document_type,
            )

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

        # Build external_id from source.id + doc.id
        external_id = f"{doc.source.id}-{doc.id}"

        # Upsert the document
        result = await self._db.fetchrow(
            """
            INSERT INTO document (
                external_id, title, url, summary,
                jurisdiction_id, region_id, document_type_id,
                document_number, publish_id,
                ingest_date, valid_from, valid_to, publish_date,
                legal_status, source_id, meta
            ) VALUES (
                $1, $2, $3, $4,
                $5::uuid, $6::uuid, $7::uuid,
                $8, $9,
                $10, $11, $12, $13,
                $14, $15::uuid, $16
            )
            ON CONFLICT (external_id) DO UPDATE
                SET title = EXCLUDED.title,
                    url = EXCLUDED.url,
                    summary = COALESCE(EXCLUDED.summary, document.summary),
                    jurisdiction_id = COALESCE($5::uuid, document.jurisdiction_id),
                    region_id = COALESCE($6::uuid, document.region_id),
                    document_type_id = COALESCE($7::uuid, document.document_type_id),
                    document_number = COALESCE(EXCLUDED.document_number, document.document_number),
                    publish_id = COALESCE(EXCLUDED.publish_id, document.publish_id),
                    ingest_date = EXCLUDED.ingest_date,
                    valid_from = COALESCE(EXCLUDED.valid_from, document.valid_from),
                    valid_to = COALESCE(EXCLUDED.valid_to, document.valid_to),
                    publish_date = COALESCE(EXCLUDED.publish_date, document.publish_date),
                    legal_status = EXCLUDED.legal_status,
                    meta = COALESCE(EXCLUDED.meta, document.meta),
                    updated_at = now()
            RETURNING id
            """,
            external_id,
            doc.title,
            doc.url,
            doc.summary,
            jurisdiction_id,
            region_id,
            doc_type_id,
            doc.document_number,
            doc.publish_id,
            doc.ingest_date,
            doc.valid_from,
            doc.valid_to,
            doc.publish_date,
            doc.legal_status.value
            if isinstance(doc.legal_status, LegalStatus)
            else doc.legal_status,
            source_uuid,
            _serialize_meta(doc.meta),
        )

        assert result is not None
        doc_uuid = str(result["id"])

        # Upsert organizations (M:N)
        if doc.organization:
            await self._upsert_document_organizations(doc_uuid, source_uuid, doc.organization)

        # Upsert topics (M:N)
        if doc.topic:
            await self._upsert_document_topics(doc_uuid, source_uuid, doc.topic)

        return doc_uuid

    async def _upsert_document_organizations(
        self,
        doc_uuid: str,
        source_uuid: str,
        organizations: list[str],
    ) -> None:
        """Upsert M:N document_organization records."""
        for org_name in organizations:
            org_id = await self._ref_repo.get_or_create_organization(
                source_id=source_uuid,
                external_id=org_name,
                name=org_name,
            )
            if org_id is not None:
                await self._db.execute(
                    """
                    INSERT INTO document_organization (document_id, organization_id)
                    VALUES ($1::uuid, $2::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    doc_uuid,
                    org_id,
                )

    async def _upsert_document_topics(
        self,
        doc_uuid: str,
        source_uuid: str,
        topics: list[str],
    ) -> None:
        """Upsert M:N document_topic records."""
        for topic_name in topics:
            topic_id = await self._ref_repo.get_or_create_topic(
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

    async def get_document_by_external_id(
        self,
        external_id: str,
    ) -> OfficialDocument | None:
        """Get a document by its external_id. Returns None if not found or on error."""
        row = await self._db.fetchrow(
            """
            SELECT
                d.id, d.external_id, d.title, d.url, d.summary,
                d.document_number, d.publish_id,
                d.ingest_date, d.valid_from, d.valid_to, d.publish_date,
                d.legal_status, d.meta,
                ds.source_id as source_source_id,
                ds.name as source_name,
                ds.url as source_url,
                ds.jurisdiction as source_jurisdiction,
                dt.name as doc_type_name,
                j.name as jurisdiction_name,
                r.name as region_name
            FROM document d
            JOIN data_source ds ON ds.id = d.source_id
            LEFT JOIN document_type dt ON dt.id = d.document_type_id
            LEFT JOIN jurisdiction j ON j.id = d.jurisdiction_id
            LEFT JOIN region r ON r.id = d.region_id
            WHERE d.external_id = $1
            """,
            external_id,
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
            """
            SELECT
                d.id, d.external_id, d.title, d.url, d.summary,
                d.document_number, d.publish_id,
                d.ingest_date, d.valid_from, d.valid_to, d.publish_date,
                d.legal_status, d.meta,
                ds.source_id as source_source_id,
                ds.name as source_name,
                ds.url as source_url,
                ds.jurisdiction as source_jurisdiction,
                dt.name as doc_type_name,
                j.name as jurisdiction_name,
                r.name as region_name
            FROM document d
            JOIN data_source ds ON ds.id = d.source_id
            LEFT JOIN document_type dt ON dt.id = d.document_type_id
            LEFT JOIN jurisdiction j ON j.id = d.jurisdiction_id
            LEFT JOIN region r ON r.id = d.region_id
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
        # Fetch organizations and topics for this document
        orgs = await self._get_document_organizations(str(row["id"]))
        topics = await self._get_document_topics(str(row["id"]))

        legal_status_str = row["legal_status"] or "unknown"
        try:
            legal_status = LegalStatus(legal_status_str)
        except ValueError:
            legal_status = LegalStatus.UNKNOWN

        return OfficialDocument(
            id=str(row["external_id"]),
            title=row["title"],
            source=Source(
                id=row["source_source_id"],
                name=row["source_name"],
                url=row["source_url"],
                jurisdiction=row["source_jurisdiction"],
            ),
            url=row["url"],
            summary=row["summary"],
            jurisdiction=row["jurisdiction_name"],
            region=row["region_name"],
            topic=topics,
            organization=orgs,
            ingest_date=_ensure_datetime(row["ingest_date"]),
            valid_from=_ensure_datetime(row["valid_from"]),
            valid_to=_ensure_datetime(row["valid_to"]),
            legal_status=legal_status,
            document_number=row["document_number"],
            document_type=row["doc_type_name"],
            publish_id=row["publish_id"],
            publish_date=_ensure_datetime(row["publish_date"]),
            meta=_deserialize_meta(row["meta"]),
        )

    async def _get_document_organizations(
        self,
        doc_uuid: str,
    ) -> list[str]:
        """Get organization names for a document."""
        rows = await self._db.fetch(
            """
            SELECT o.name
            FROM document_organization do
            JOIN organization o ON o.id = do.organization_id
            WHERE do.document_id = $1::uuid
            ORDER BY o.name
            """,
            doc_uuid,
        )
        if rows is None:
            return []
        return [r["name"] for r in rows]

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
        rows = await self._db.fetch(
            """
            SELECT
                d.id, d.external_id, d.title, d.url, d.summary,
                d.document_number, d.publish_id,
                d.ingest_date, d.valid_from, d.valid_to, d.publish_date,
                d.legal_status, d.meta,
                ds.source_id as source_source_id,
                ds.name as source_name,
                ds.url as source_url,
                ds.jurisdiction as source_jurisdiction,
                dt.name as doc_type_name,
                j.name as jurisdiction_name,
                r.name as region_name
            FROM document d
            JOIN data_source ds ON ds.id = d.source_id
            LEFT JOIN document_type dt ON dt.id = d.document_type_id
            LEFT JOIN jurisdiction j ON j.id = d.jurisdiction_id
            LEFT JOIN region r ON r.id = d.region_id
            WHERE d.title ILIKE $1
            ORDER BY d.ingest_date DESC
            LIMIT $2 OFFSET $3
            """,
            search_pattern,
            limit,
            offset,
        )
        if rows is None:
            return []

        documents: list[OfficialDocument] = []
        for row in rows:
            doc = await self._row_to_document(row)
            if doc is not None:
                documents.append(doc)
        return documents


def _serialize_meta(meta: dict[str, Any] | None) -> str | None:
    """Serialize meta dict to JSON string for JSONB column."""
    if not meta:
        return None

    return json.dumps(meta, default=str)


def _deserialize_meta(meta: Any) -> dict[str, Any]:
    """Deserialize JSONB value to dict."""
    if meta is None:
        return {}
    if isinstance(meta, dict):
        return meta

    try:
        return json.loads(meta) if isinstance(meta, str) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _ensure_datetime(val: Any) -> datetime | None:
    """Ensure a value is a datetime or None."""
    if val is None:
        return None
    if isinstance(val, datetime):
        # Ensure timezone-aware
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    return None


__all__ = [
    "DocumentRepository",
]
