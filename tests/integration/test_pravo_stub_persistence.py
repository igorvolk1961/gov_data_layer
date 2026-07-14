"""Integration tests for PravoAdapter stub mode with PostgreSQL persistence.

Tests the full pipeline: real HTTP requests to pravo.gov.ru → parsing →
canonical OfficialDocument model → PostgreSQL persistence.

These tests verify that:
1. adapter.get() persists documents to PostgreSQL when db is configured
2. adapter.ingest() persists all documents to PostgreSQL
3. adapter.get() works correctly without db (no persistence, no crash)
4. Persisted document fields match the original OfficialDocument
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from adapters.pravo.adapter import PravoAdapter
from adapters.pravo.adapter.stub._data import _STUB_PUBLISH_IDS_INITIAL
from core.models.models import OfficialDocument
from core.persistence import DatabaseClient
from core.persistence.repository import DocumentRepository, ReferenceRepository


@pytest_asyncio.fixture
async def adapter_with_db(db: DatabaseClient) -> PravoAdapter:
    """Create a PravoAdapter in stub mode with DB persistence."""
    adapter = PravoAdapter(mode="stub", db=db)
    try:
        yield adapter
    finally:
        await adapter.close()


@pytest.fixture
def adapter_without_db() -> PravoAdapter:
    """Create a PravoAdapter in stub mode without DB persistence."""
    return PravoAdapter(mode="stub")


@pytest_asyncio.fixture
async def doc_repo(db: DatabaseClient) -> DocumentRepository:
    """Create a DocumentRepository for reading from the database."""
    ref_repo = ReferenceRepository(db)
    return DocumentRepository(db, ref_repo)


async def _cleanup_test_documents(db: DatabaseClient) -> None:
    """Remove test documents persisted by these tests."""
    await db.execute(
        "DELETE FROM document WHERE publish_id LIKE '0001%'",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_persists_document_to_db(
    adapter_with_db: PravoAdapter,
    db: DatabaseClient,
    doc_repo: DocumentRepository,
) -> None:
    """After adapter.get(), the document should be persisted to PostgreSQL."""
    publish_id = _STUB_PUBLISH_IDS_INITIAL[0]
    document_id = f"pravo-{publish_id}"

    try:
        # Act: get document (should persist to DB)
        doc = await adapter_with_db.get(document_id)
        assert isinstance(doc, OfficialDocument)

        # Assert: document exists in DB
        publish_id = doc.publish_id
        db_doc = await doc_repo.get_document_by_publish_id(publish_id)
        assert db_doc is not None, f"Document {publish_id} not found in DB"
        assert db_doc.title == doc.title
        assert db_doc.document_number == doc.document_number
        assert db_doc.publish_id == doc.publish_id
        assert db_doc.url == doc.url
    finally:
        await _cleanup_test_documents(db)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_persists_all_documents_to_db(
    adapter_with_db: PravoAdapter,
    db: DatabaseClient,
    doc_repo: DocumentRepository,
) -> None:
    """After adapter.ingest(), all documents should be persisted to PostgreSQL."""
    try:
        # Act: ingest all documents
        count = await adapter_with_db.ingest()
        assert count == len(_STUB_PUBLISH_IDS_INITIAL)

        # Assert: each document exists in DB
        for pub_id in _STUB_PUBLISH_IDS_INITIAL:
            document_id = f"pravo-{pub_id}"
            db_doc = await doc_repo.get_document_by_publish_id(pub_id)
            assert db_doc is not None, f"Document {document_id} not found in DB after ingest"
            assert db_doc.title, f"Document {document_id} has no title in DB"
            assert db_doc.publish_id == pub_id
    finally:
        await _cleanup_test_documents(db)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_without_db_does_not_persist(
    adapter_without_db: PravoAdapter,
    db: DatabaseClient,  # noqa: ARG001 — needed by doc_repo fixture dependency chain
    doc_repo: DocumentRepository,
) -> None:
    """Without db, adapter.get() should work but not persist to PostgreSQL."""
    publish_id = _STUB_PUBLISH_IDS_INITIAL[0]
    document_id = f"pravo-{publish_id}"

    # Act: get document without DB
    doc = await adapter_without_db.get(document_id)
    assert isinstance(doc, OfficialDocument)

    # Assert: document should NOT exist in DB
    external_id = doc.publish_id
    db_doc = await doc_repo.get_document_by_publish_id(external_id)
    assert db_doc is None, f"Document {external_id} should not exist in DB when adapter has no db"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_persisted_document_fields_match(
    adapter_with_db: PravoAdapter,
    db: DatabaseClient,
    doc_repo: DocumentRepository,
) -> None:
    """Verify all significant fields match between adapter.get() and DB read."""
    publish_id = _STUB_PUBLISH_IDS_INITIAL[0]
    document_id = f"pravo-{publish_id}"

    try:
        # Act: get document from adapter
        doc = await adapter_with_db.get(document_id)
        assert isinstance(doc, OfficialDocument)

        # Read from DB
        db_doc = await doc_repo.get_document_by_publish_id(doc.publish_id)
        assert db_doc is not None

        # Assert: fields match
        assert db_doc.title == doc.title, f"Title mismatch: {db_doc.title} != {doc.title}"
        assert db_doc.url == doc.url, f"URL mismatch: {db_doc.url} != {doc.url}"
        assert db_doc.summary == doc.summary, f"Summary mismatch: {db_doc.summary} != {doc.summary}"
        assert db_doc.document_number == doc.document_number, (
            f"Document number mismatch: {db_doc.document_number} != {doc.document_number}"
        )
        assert db_doc.publish_id == doc.publish_id, (
            f"Publish ID mismatch: {db_doc.publish_id} != {doc.publish_id}"
        )
        assert db_doc.legal_status == doc.legal_status, (
            f"Legal status mismatch: {db_doc.legal_status} != {doc.legal_status}"
        )
        assert db_doc.publish_date == doc.publish_date, (
            f"Publish date mismatch: {db_doc.publish_date} != {doc.publish_date}"
        )
        assert db_doc.valid_from == doc.valid_from, (
            f"Valid from mismatch: {db_doc.valid_from} != {doc.valid_from}"
        )
        assert db_doc.created_at == doc.created_at, (
            f"Created at mismatch: {db_doc.created_at} != {doc.created_at}"
        )
    finally:
        await _cleanup_test_documents(db)
