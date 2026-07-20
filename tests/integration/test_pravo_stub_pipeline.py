"""Integration tests for PravoAdapter stub mode with real HTTP calls.

Tests the full pipeline: real HTTP requests to pravo.gov.ru → parsing →
canonical OfficialDocument model. No mocks — all tests make real API calls.

These tests verify that:
1. StubIngestHandler fetches all documents from _STUB_PUBLISH_IDS_INITIAL
2. StubGetHandler returns fully populated OfficialDocument models
3. All canonical model fields are correctly filled from parsed API data
4. Caching works across multiple get() calls
5. Error handling for non-existent documents
"""

from __future__ import annotations

import pytest

from adapters.pravo.adapter import PravoAdapter
from adapters.pravo.adapter.stub._data import _STUB_PUBLISH_IDS_INITIAL
from core.errors import NotFoundError
from core.models.models import LegalStatus, OfficialDocument


@pytest.fixture
def adapter() -> PravoAdapter:
    """Create a PravoAdapter in stub mode with real HTTP client.

    No mocks — all calls go to the real pravo.gov.ru API.
    """
    return PravoAdapter(mode="stub")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.slow
async def test_stub_ingest_fetches_all_documents(adapter: PravoAdapter) -> None:
    """Ingest should fetch all documents from _STUB_PUBLISH_IDS_INITIAL.

    Verifies that the full pipeline (HTTP → parse → model) works
    for every document in the fixed publish_id list.
    """
    count = await adapter.ingest()
    assert count == len(_STUB_PUBLISH_IDS_INITIAL), (
        f"Expected {len(_STUB_PUBLISH_IDS_INITIAL)} documents, got {count}"
    )


@pytest.mark.asyncio
async def test_stub_get_returns_canonical_model(adapter: PravoAdapter) -> None:
    """Get a document by ID and verify it's a fully populated OfficialDocument.

    Tests the full HTTP → parse → model pipeline for a single document.
    """
    document_id = f"pravo-{_STUB_PUBLISH_IDS_INITIAL[0]}"
    doc = await adapter.get(document_id)

    # Verify it's an OfficialDocument
    assert isinstance(doc, OfficialDocument), f"Expected OfficialDocument, got {type(doc)}"

    # Verify core identity fields
    assert doc.id == document_id, f"Document ID mismatch: {doc.id} != {document_id}"
    assert doc.publish_id == _STUB_PUBLISH_IDS_INITIAL[0], (
        f"Publish ID mismatch: {doc.publish_id} != {_STUB_PUBLISH_IDS_INITIAL[0]}"
    )
    assert doc.title, "Document title is empty"
    assert doc.source is not None, "Document source is missing"
    assert doc.source.id == "pravo", f"Source ID mismatch: {doc.source.id}"

    # Verify URL is populated
    assert doc.url, "Document URL is empty"
    assert _STUB_PUBLISH_IDS_INITIAL[0] in doc.url, f"URL does not contain publish_id: {doc.url}"

    # Verify document metadata
    assert doc.document_number, "Document number is empty"
    # NOTE: document_type may be None until doc_type_cache is populated
    # (see PravoParser.__init__ TODO)
    if doc.document_type:
        assert isinstance(doc.document_type, str), (
            f"document_type should be str, got {type(doc.document_type)}"
        )
    # NOTE: jurisdiction may be None if not provided by the source
    # organization may contain raw GUIDs until authority_cache is populated
    # (see PravoParser.__init__ TODO)

    # Verify dates
    assert doc.publish_date is not None, "Publish date is missing"
    assert doc.valid_from is not None, "Valid from date is missing"
    assert doc.created_at is not None, "Created at is missing"

    # Verify legal status
    assert doc.legal_status is not None, "Legal status is missing"
    assert doc.legal_status in (
        LegalStatus.ACTIVE,
        LegalStatus.REVOKED,
        LegalStatus.MODIFIED,
        LegalStatus.UNKNOWN,
    ), f"Unexpected legal status: {doc.legal_status}"

    # Verify topics (may be empty until topic cache is populated)
    # NOTE: topics may be empty — this is a known limitation of PravoParser
    assert isinstance(doc.topic, list), f"topic should be a list, got {type(doc.topic)}"

    # Verify summary
    assert doc.summary, "Summary is empty"


@pytest.mark.asyncio
async def test_stub_get_all_documents(adapter: PravoAdapter) -> None:
    """Fetch each document from _STUB_PUBLISH_IDS_INITIAL and verify all are valid.

    This is the main integration test — it exercises the full pipeline
    for every document in the fixed list and validates canonical models.
    """
    for publish_id in _STUB_PUBLISH_IDS_INITIAL:
        document_id = f"pravo-{publish_id}"
        doc = await adapter.get(document_id)

        assert isinstance(doc, OfficialDocument), (
            f"Document {document_id}: expected OfficialDocument, got {type(doc)}"
        )
        assert doc.id == document_id, f"Document {document_id}: ID mismatch"
        assert doc.publish_id == publish_id, f"Document {document_id}: publish_id mismatch"
        assert doc.title, f"Document {document_id}: title is empty"
        assert doc.document_number, f"Document {document_id}: document_number is empty"
        # NOTE: document_type may be None until doc_type_cache is populated
        # (see PravoParser.__init__ TODO)
        # NOTE: organization may contain raw GUIDs until authority_cache is populated
        # (see PravoParser.__init__ TODO)
        assert doc.publish_date is not None, f"Document {document_id}: publish_date is missing"
        assert doc.valid_from is not None, f"Document {document_id}: valid_from is missing"
        assert doc.legal_status is not None, f"Document {document_id}: legal_status is missing"
        assert doc.url, f"Document {document_id}: url is empty"
        assert doc.summary, f"Document {document_id}: summary is empty"

        # Log document info for debugging
        doc_type_str = doc.document_type or "?"
        print(f"  ✓ {document_id}: {doc.title} ({doc_type_str} #{doc.document_number})")


@pytest.mark.asyncio
async def test_stub_get_caches_documents(adapter: PravoAdapter) -> None:
    """After fetching a document, it should be cached in adapter._document_cache."""
    document_id = f"pravo-{_STUB_PUBLISH_IDS_INITIAL[0]}"

    # First call: fetches from API and caches
    doc1 = await adapter.get(document_id)
    assert doc1 is not None

    # Verify it's in the cache
    assert document_id in adapter._document_cache, (
        f"Document {document_id} not found in cache after fetch"
    )

    # Second call: should return from cache (or API, but either way works)
    doc2 = await adapter.get(document_id)
    assert doc2 is not None
    assert doc2.id == doc1.id
    assert doc2.title == doc1.title


@pytest.mark.asyncio
async def test_stub_get_raises_not_found_for_missing_document(
    adapter: PravoAdapter,
) -> None:
    """Requesting a non-existent document should raise NotFoundError."""
    non_existent_id = "pravo-0000000000000000"

    with pytest.raises(NotFoundError) as exc_info:
        await adapter.get(non_existent_id)

    error_msg = str(exc_info.value)
    assert non_existent_id in error_msg, f"Error message should contain document ID: {error_msg}"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.slow
async def test_stub_ingest_populates_cache(adapter: PravoAdapter) -> None:
    """After ingest, all documents should be in the adapter's cache."""
    count = await adapter.ingest()
    assert count == len(_STUB_PUBLISH_IDS_INITIAL)

    # Verify all documents are cached
    for publish_id in _STUB_PUBLISH_IDS_INITIAL:
        document_id = f"pravo-{publish_id}"
        assert document_id in adapter._document_cache, (
            f"Document {document_id} not cached after ingest"
        )

        # Verify cached document is valid
        cached_doc, _ = adapter._document_cache[document_id]
        assert isinstance(cached_doc, OfficialDocument)
        assert cached_doc.id == document_id
        assert cached_doc.title, f"Cached document {document_id} has no title"
