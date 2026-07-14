"""Integration tests for DatabaseClient helpers with real PostgreSQL.

These tests connect to the metadata-db container (postgresql://odl:odl@localhost:5432/odl_metadata)
and verify that the helpers work correctly against a real database.

Prerequisites:
    - Docker containers are running: docker compose up -d metadata-db liquibase
    - Liquibase migrations have been applied

Run with:
    pytest tests/integration/test_persistence_helpers.py -v --no-header
"""

from __future__ import annotations

import uuid

import pytest

from core.persistence.db_client import DatabaseClient

# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_insert_mode(db: DatabaseClient) -> None:
    """Verify upsert() inserts a new row and returns the generated UUID."""
    # First insert a data_source to satisfy the FK constraint
    src = await db.upsert(
        table="data_source",
        data={
            "source_id": "upsert-insert-source",
            "name": "Upsert Insert Source",
            "url": "https://example.com",
            "jurisdiction": "test",
        },
        conflict_columns=["source_id"],
    )
    assert src is not None
    source_id = str(src["id"])

    result = await db.upsert(
        table="document_type",
        data={
            "source_id": source_id,
            "external_id": "upsert-insert-test",
            "name": "Upsert Insert Test",
        },
        conflict_columns=["source_id", "external_id"],
    )
    assert result is not None
    assert "id" in result

    # Verify the row was actually inserted
    row = await db.fetchrow(
        "SELECT name FROM document_type WHERE id = $1::uuid",
        result["id"],
    )
    assert row is not None
    assert row["name"] == "Upsert Insert Test"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_update_mode(
    db: DatabaseClient,
    source_uuid: str,
) -> None:
    """Verify upsert() updates an existing row and returns the same UUID."""
    # First insert
    result1 = await db.upsert(
        table="document_type",
        data={
            "source_id": source_uuid,
            "external_id": "upsert-update-test",
            "name": "Original Name",
        },
        conflict_columns=["source_id", "external_id"],
    )
    assert result1 is not None
    original_id = str(result1["id"])

    # Update via upsert
    result2 = await db.upsert(
        table="document_type",
        data={
            "source_id": source_uuid,
            "external_id": "upsert-update-test",
            "name": "Updated Name",
        },
        conflict_columns=["source_id", "external_id"],
        update_columns=["name"],
    )
    assert result2 is not None
    assert str(result2["id"]) == original_id, "UUID should remain the same on update"

    # Verify the name was updated
    row = await db.fetchrow(
        "SELECT name FROM document_type WHERE id = $1::uuid",
        original_id,
    )
    assert row is not None
    assert row["name"] == "Updated Name"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_invalid_table_raises(db: DatabaseClient) -> None:
    """Verify upsert() raises ValueError for non-whitelisted tables."""
    with pytest.raises(ValueError, match="is not in the upsert whitelist"):
        await db.upsert(
            table="nonexistent_table",
            data={"id": "123"},
            conflict_columns=["id"],
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_transaction_commit(
    db: DatabaseClient,
    source_uuid: str,
) -> None:
    """Verify transaction() commits changes on success."""
    test_ext_id = f"tx-commit-{uuid.uuid4().hex[:8]}"

    async with db.transaction() as tx:
        result = await tx.upsert(
            table="document_type",
            data={
                "source_id": source_uuid,
                "external_id": test_ext_id,
                "name": "Transaction Commit Test",
            },
            conflict_columns=["source_id", "external_id"],
        )
        assert result is not None

    # Verify the row is visible outside the transaction
    row = await db.fetchrow(
        "SELECT name FROM document_type WHERE external_id = $1",
        test_ext_id,
    )
    assert row is not None
    assert row["name"] == "Transaction Commit Test"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_transaction_rollback(
    db: DatabaseClient,
    source_uuid: str,
) -> None:
    """Verify transaction() rolls back changes on exception."""
    test_ext_id = f"tx-rollback-{uuid.uuid4().hex[:8]}"

    with pytest.raises(RuntimeError, match="rollback test"):
        async with db.transaction() as tx:
            await tx.upsert(
                table="document_type",
                data={
                    "source_id": source_uuid,
                    "external_id": test_ext_id,
                    "name": "Should Not Persist",
                },
                conflict_columns=["source_id", "external_id"],
            )
            raise RuntimeError("rollback test")

    # Verify the row was NOT inserted
    row = await db.fetchrow(
        "SELECT name FROM document_type WHERE external_id = $1",
        test_ext_id,
    )
    assert row is None, "Transaction should have been rolled back"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_paginated_fetch(db: DatabaseClient) -> None:
    """Verify paginated_fetch() returns correct slices of data."""
    # Insert test data
    for i in range(10):
        await db.execute(
            "INSERT INTO rubric (id, external_id, name) VALUES (gen_random_uuid(), $1, $2) ON CONFLICT DO NOTHING",
            f"paginated-ext-{i}",
            f"paginated-rubric-{i}",
        )

    # Fetch first page (limit=3, offset=0)
    page1 = await db.paginated_fetch(
        "SELECT name FROM rubric WHERE name LIKE 'paginated-rubric-%' ORDER BY name",
        limit=3,
        offset=0,
    )
    assert len(page1) == 3
    assert page1[0]["name"] == "paginated-rubric-0"
    assert page1[1]["name"] == "paginated-rubric-1"
    assert page1[2]["name"] == "paginated-rubric-2"

    # Fetch second page (limit=3, offset=3)
    page2 = await db.paginated_fetch(
        "SELECT name FROM rubric WHERE name LIKE 'paginated-rubric-%' ORDER BY name",
        limit=3,
        offset=3,
    )
    assert len(page2) == 3
    assert page2[0]["name"] == "paginated-rubric-3"
    assert page2[1]["name"] == "paginated-rubric-4"
    assert page2[2]["name"] == "paginated-rubric-5"

    # Fetch beyond available data
    page3 = await db.paginated_fetch(
        "SELECT name FROM rubric WHERE name LIKE 'paginated-rubric-%' ORDER BY name",
        limit=3,
        offset=20,
    )
    assert len(page3) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jsonb_serialize_deserialize_roundtrip(
    db: DatabaseClient,
    source_uuid: str,
    doc_type_id: str,
    jurisdiction_id: str,
    region_id: str,
) -> None:
    """Verify JSONB serialization roundtrip through the database."""
    test_meta = {
        "key1": "value1",
        "key2": 42,
        "key3": {"nested": "data"},
        "key4": None,
    }

    # Insert a document with meta as JSONB
    result = await db.fetchrow(
        """
        INSERT INTO document (
            id, publish_id, title, summary, meta,
            source_id, document_type_id, jurisdiction_id, region_id
        ) VALUES (
            gen_random_uuid(), $1, $2, $3, $4::jsonb,
            $5::uuid, $6, $7::uuid, $8::uuid
        )
        RETURNING id
        """,
        f"jsonb-test-{uuid.uuid4().hex[:8]}",
        "JSONB Test Document",
        "Testing JSONB roundtrip",
        DatabaseClient.serialize_jsonb(test_meta),
        source_uuid,
        "test-type",  # document_type external_id (source GUID)
        jurisdiction_id,
        region_id,
    )
    assert result is not None
    doc_uuid = str(result["id"])

    # Read back and deserialize
    row = await db.fetchrow(
        "SELECT meta FROM document WHERE id = $1::uuid",
        doc_uuid,
    )
    assert row is not None

    deserialized = DatabaseClient.deserialize_jsonb(row["meta"])
    assert deserialized == test_meta


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_roundtrip_document_type(db: DatabaseClient) -> None:
    """Full roundtrip: upsert → read → upsert (update) → read."""
    # First insert a data_source to satisfy the FK constraint
    src = await db.upsert(
        table="data_source",
        data={
            "source_id": "roundtrip-source",
            "name": "Roundtrip Source",
            "url": "https://example.com",
            "jurisdiction": "test",
        },
        conflict_columns=["source_id"],
    )
    assert src is not None
    source_id = str(src["id"])

    ext_id = f"roundtrip-{uuid.uuid4().hex[:8]}"

    # Insert
    result = await db.upsert(
        table="document_type",
        data={
            "source_id": source_id,
            "external_id": ext_id,
            "name": "Roundtrip Test",
        },
        conflict_columns=["source_id", "external_id"],
    )
    assert result is not None
    doc_type_id = str(result["id"])

    # Read back
    row = await db.fetchrow(
        "SELECT name FROM document_type WHERE id = $1::uuid",
        doc_type_id,
    )
    assert row is not None
    assert row["name"] == "Roundtrip Test"

    # Update
    result2 = await db.upsert(
        table="document_type",
        data={
            "source_id": source_id,
            "external_id": ext_id,
            "name": "Updated Roundtrip",
        },
        conflict_columns=["source_id", "external_id"],
        update_columns=["name"],
    )
    assert result2 is not None
    assert str(result2["id"]) == doc_type_id

    # Read back updated
    row2 = await db.fetchrow(
        "SELECT name FROM document_type WHERE id = $1::uuid",
        doc_type_id,
    )
    assert row2 is not None
    assert row2["name"] == "Updated Roundtrip"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_transaction_proxy_all_methods(
    db: DatabaseClient,
    source_uuid: str,
) -> None:
    """Verify TransactionProxy exposes all needed methods within a transaction."""
    test_ext_id = f"tx-proxy-{uuid.uuid4().hex[:8]}"

    async with db.transaction() as tx:
        # fetchrow
        row = await tx.fetchrow("SELECT 1 AS val")
        assert row is not None
        assert row["val"] == 1

        # fetch
        rows = await tx.fetch("SELECT 1 AS val UNION ALL SELECT 2 AS val")
        assert len(rows) == 2

        # fetchval
        val = await tx.fetchval("SELECT 42")
        assert val == 42

        # execute
        result = await tx.execute(
            """
            INSERT INTO document_type (id, source_id, external_id, name)
            VALUES (gen_random_uuid(), $1::uuid, $2, $3)
            ON CONFLICT DO NOTHING
            """,
            source_uuid,
            test_ext_id,
            "TransactionProxy Test",
        )
        assert isinstance(result, str)

        # executemany
        await tx.executemany(
            """
            INSERT INTO rubric (id, external_id, name) VALUES (gen_random_uuid(), $1, $2)
            ON CONFLICT DO NOTHING
            """,
            [("tx-proxy-ext-1", "tx-proxy-rubric-1"), ("tx-proxy-ext-2", "tx-proxy-rubric-2")],
        )

    # Verify data persisted
    row = await db.fetchrow(
        "SELECT name FROM document_type WHERE external_id = $1",
        test_ext_id,
    )
    assert row is not None
    assert row["name"] == "TransactionProxy Test"
