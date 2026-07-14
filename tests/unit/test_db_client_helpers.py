"""Unit tests for DatabaseClient helper methods (upsert, transaction, etc.)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.persistence.db_client import DatabaseClient


class _FakeRecord:
    """Minimal fake for asyncpg.Record that supports dict-like access."""

    def __init__(self, **kwargs: object) -> None:
        self._data = kwargs

    def __getitem__(self, key: str) -> object:
        return self._data[key]


@pytest.fixture
def db() -> DatabaseClient:
    """Create a DatabaseClient with a mocked pool."""
    client = DatabaseClient(dsn="postgresql://test:test@localhost:5432/test")
    client._pool = MagicMock()
    return client


@pytest.fixture
def mock_conn(db: DatabaseClient) -> MagicMock:
    """Return the mock connection acquired from the pool.

    Sets up pool.acquire() as an async context manager that returns conn.
    """
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_FakeRecord(id="some-uuid"))

    # pool.acquire() returns an async context manager
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    db._pool.acquire = MagicMock(return_value=acquire_cm)

    return conn


class TestUpsert:
    """Tests for DatabaseClient.upsert()."""

    @pytest.mark.asyncio
    async def test_upsert_generates_correct_sql(
        self, db: DatabaseClient, mock_conn: MagicMock
    ) -> None:
        """Verify that upsert() generates SQL with INSERT, ON CONFLICT, DO UPDATE, RETURNING."""
        result = await db.upsert(
            table="document_type",
            data={"source_id": "s1", "external_id": "e1", "name": "Test"},
            conflict_columns=["source_id", "external_id"],
        )

        assert result is not None
        mock_conn.fetchrow.assert_called_once()
        sql = mock_conn.fetchrow.call_args[0][0]

        assert sql.startswith("INSERT INTO document_type")
        assert "ON CONFLICT (source_id, external_id)" in sql
        assert "DO UPDATE SET" in sql
        assert "RETURNING id" in sql
        # conflict_columns are excluded from SET when update_columns=None
        assert "source_id = EXCLUDED.source_id" not in sql
        assert "external_id = EXCLUDED.external_id" not in sql
        assert "name = EXCLUDED.name" in sql

    @pytest.mark.asyncio
    async def test_upsert_insert_mode(self, db: DatabaseClient, mock_conn: MagicMock) -> None:
        """Verify upsert returns a record on insert (no conflict)."""
        mock_conn.fetchrow = AsyncMock(return_value=_FakeRecord(id="new-uuid"))

        result = await db.upsert(
            table="document_type",
            data={"source_id": "s1", "external_id": "e1", "name": "New Type"},
            conflict_columns=["source_id", "external_id"],
        )

        assert result is not None
        assert result["id"] == "new-uuid"

    @pytest.mark.asyncio
    async def test_upsert_update_mode(self, db: DatabaseClient, mock_conn: MagicMock) -> None:
        """Verify upsert returns the existing record on conflict (update)."""
        mock_conn.fetchrow = AsyncMock(return_value=_FakeRecord(id="existing-uuid"))

        result = await db.upsert(
            table="document_type",
            data={"source_id": "s1", "external_id": "e1", "name": "Updated Type"},
            conflict_columns=["source_id", "external_id"],
        )

        assert result is not None
        assert result["id"] == "existing-uuid"

    @pytest.mark.asyncio
    async def test_upsert_invalid_table_raises(self, db: DatabaseClient) -> None:
        """Verify ValueError for table not in whitelist."""
        with pytest.raises(ValueError, match="not in the upsert whitelist"):
            await db.upsert(
                table="nonexistent_table",
                data={"name": "test"},
                conflict_columns=["id"],
            )

    @pytest.mark.asyncio
    async def test_upsert_empty_data_raises(self, db: DatabaseClient) -> None:
        """Verify ValueError for empty data dict."""
        with pytest.raises(ValueError, match="data must not be empty"):
            await db.upsert(
                table="document_type",
                data={},
                conflict_columns=["id"],
            )

    @pytest.mark.asyncio
    async def test_upsert_empty_conflict_columns_raises(self, db: DatabaseClient) -> None:
        """Verify ValueError for empty conflict_columns."""
        with pytest.raises(ValueError, match="conflict_columns must not be empty"):
            await db.upsert(
                table="document_type",
                data={"name": "test"},
                conflict_columns=[],
            )

    @pytest.mark.asyncio
    async def test_upsert_update_columns_subset(
        self, db: DatabaseClient, mock_conn: MagicMock
    ) -> None:
        """Verify only specified update_columns are included in SET clause."""
        await db.upsert(
            table="document_type",
            data={"source_id": "s1", "external_id": "e1", "name": "Test", "weight": 10},
            conflict_columns=["source_id", "external_id"],
            update_columns=["name"],
        )

        sql = mock_conn.fetchrow.call_args[0][0]
        assert "name = EXCLUDED.name" in sql
        assert "weight = EXCLUDED.weight" not in sql
        assert "source_id = EXCLUDED.source_id" not in sql
        assert "external_id = EXCLUDED.external_id" not in sql

    @pytest.mark.asyncio
    async def test_upsert_custom_returning(self, db: DatabaseClient, mock_conn: MagicMock) -> None:
        """Verify custom RETURNING column is used."""
        await db.upsert(
            table="document_type",
            data={"source_id": "s1", "external_id": "e1", "name": "Test"},
            conflict_columns=["source_id", "external_id"],
            returning="external_id",
        )

        sql = mock_conn.fetchrow.call_args[0][0]
        assert "RETURNING external_id" in sql

    @pytest.mark.asyncio
    async def test_upsert_update_columns_not_in_data_raises(self, db: DatabaseClient) -> None:
        """Verify ValueError when update_column is not in data keys."""
        with pytest.raises(ValueError, match="update_column 'nonexistent' not found in data keys"):
            await db.upsert(
                table="document_type",
                data={"source_id": "s1", "external_id": "e1", "name": "Test"},
                conflict_columns=["source_id", "external_id"],
                update_columns=["nonexistent"],
            )

    @pytest.mark.asyncio
    async def test_upsert_parameters_passed_correctly(
        self, db: DatabaseClient, mock_conn: MagicMock
    ) -> None:
        """Verify that values are passed as positional args to fetchrow."""
        await db.upsert(
            table="document_type",
            data={"source_id": "s1", "external_id": "e1", "name": "Test"},
            conflict_columns=["source_id", "external_id"],
        )

        args = mock_conn.fetchrow.call_args[0]
        # args[0] is SQL, args[1:] are values
        assert args[1] == "s1"
        assert args[2] == "e1"
        assert args[3] == "Test"

    @pytest.mark.asyncio
    async def test_upsert_not_connected_raises(self) -> None:
        """Verify ConnectionError when pool is not initialized."""
        db = DatabaseClient(dsn="postgresql://test:test@localhost:5432/test")
        # _pool is None — not connected

        with pytest.raises(ConnectionError, match="not connected"):
            await db.upsert(
                table="document_type",
                data={"name": "test"},
                conflict_columns=["id"],
            )

    @pytest.mark.asyncio
    async def test_upsert_all_allowed_tables(
        self, db: DatabaseClient, mock_conn: MagicMock
    ) -> None:
        """Verify all tables in the whitelist are accepted."""
        allowed_tables = [
            "document",
            "document_section",
            "data_source",
            "document_type",
            "organization",
            "jurisdiction",
            "region",
            "topic",
            "rubric",
        ]
        for table in allowed_tables:
            mock_conn.fetchrow.reset_mock()
            mock_conn.fetchrow = AsyncMock(return_value=_FakeRecord(id="uuid"))

            result = await db.upsert(
                table=table,
                data={"source_id": "s1", "external_id": "e1", "name": "Test"},
                conflict_columns=["source_id", "external_id"],
            )
            assert result is not None, f"Failed for table '{table}'"


class TestJsonbHelpers:
    """Tests for DatabaseClient.serialize_jsonb / deserialize_jsonb."""

    # --- serialize_jsonb ---

    def test_serialize_none(self) -> None:
        assert DatabaseClient.serialize_jsonb(None) is None

    def test_serialize_empty_dict(self) -> None:
        assert DatabaseClient.serialize_jsonb({}) is None

    def test_serialize_simple(self) -> None:
        result = DatabaseClient.serialize_jsonb({"key": "value"})
        assert result == '{"key": "value"}'

    def test_serialize_unicode(self) -> None:
        result = DatabaseClient.serialize_jsonb({"text": "привет"})
        assert result == '{"text": "привет"}'

    def test_serialize_datetime_fallback(self) -> None:
        """Verify non-serializable types use default=str fallback."""
        from datetime import datetime

        dt = datetime(2025, 1, 15, 10, 30, 0)
        result = DatabaseClient.serialize_jsonb({"created": dt})
        assert "2025-01-15" in result  # str representation

    # --- deserialize_jsonb ---

    def test_deserialize_none(self) -> None:
        assert DatabaseClient.deserialize_jsonb(None) == {}

    def test_deserialize_dict_passthrough(self) -> None:
        assert DatabaseClient.deserialize_jsonb({"a": 1}) == {"a": 1}

    def test_deserialize_json_string(self) -> None:
        assert DatabaseClient.deserialize_jsonb('{"a": 1}') == {"a": 1}

    def test_deserialize_invalid_string(self) -> None:
        assert DatabaseClient.deserialize_jsonb("not json") == {}

    def test_deserialize_non_string_non_dict(self) -> None:
        assert DatabaseClient.deserialize_jsonb(42) == {}

    def test_deserialize_empty_string(self) -> None:
        assert DatabaseClient.deserialize_jsonb("") == {}


class TestPaginatedFetch:
    """Tests for DatabaseClient.paginated_fetch()."""

    @pytest.fixture
    def db_not_connected(self) -> DatabaseClient:
        """DatabaseClient with _pool = None (not connected)."""
        return DatabaseClient(dsn="postgresql://test:test@localhost:5432/test")

    @pytest.mark.asyncio
    async def test_appends_limit_offset(self, db: DatabaseClient) -> None:
        """Verify LIMIT and OFFSET are appended with correct positional params."""
        db.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await db.paginated_fetch(
            "SELECT * FROM documents WHERE name = $1", "test", limit=10, offset=5
        )

        db.fetch.assert_awaited_once()
        sql = db.fetch.call_args[0][0]
        assert sql == "SELECT * FROM documents WHERE name = $1 LIMIT $2 OFFSET $3"
        args = db.fetch.call_args[0][1:]
        assert args == ("test", 10, 5)

    @pytest.mark.asyncio
    async def test_strips_trailing_semicolon(self, db: DatabaseClient) -> None:
        """Verify trailing semicolon is stripped before appending LIMIT/OFFSET."""
        db.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await db.paginated_fetch("SELECT * FROM docs;", limit=5, offset=0)

        sql = db.fetch.call_args[0][0]
        assert sql == "SELECT * FROM docs LIMIT $1 OFFSET $2"

    @pytest.mark.asyncio
    async def test_no_args(self, db: DatabaseClient) -> None:
        """Verify LIMIT $1 OFFSET $2 when no positional args exist."""
        db.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await db.paginated_fetch("SELECT * FROM docs", limit=25, offset=10)

        sql = db.fetch.call_args[0][0]
        assert sql == "SELECT * FROM docs LIMIT $1 OFFSET $2"
        args = db.fetch.call_args[0][1:]
        assert args == (25, 10)

    @pytest.mark.asyncio
    async def test_passes_timeout(self, db: DatabaseClient) -> None:
        """Verify timeout is forwarded to fetch()."""
        db.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await db.paginated_fetch("SELECT * FROM docs", limit=5, offset=0, timeout=3.0)

        db.fetch.assert_awaited_once_with(
            "SELECT * FROM docs LIMIT $1 OFFSET $2", 5, 0, timeout=3.0
        )

    @pytest.mark.asyncio
    async def test_returns_records(self, db: DatabaseClient) -> None:
        """Verify records are returned from fetch()."""
        expected = [_FakeRecord(id="r1"), _FakeRecord(id="r2")]
        db.fetch = AsyncMock(return_value=expected)  # type: ignore[method-assign]

        result = await db.paginated_fetch("SELECT * FROM docs", limit=2, offset=0)

        assert result == expected

    @pytest.mark.asyncio
    async def test_not_connected_raises(self, db_not_connected: DatabaseClient) -> None:
        """Verify ConnectionError when pool is not initialized."""
        with pytest.raises(ConnectionError, match="not connected"):
            await db_not_connected.paginated_fetch("SELECT 1", limit=10, offset=0)


class TestTransaction:
    """Tests for DatabaseClient.transaction() and TransactionProxy."""

    @pytest.fixture
    def db_not_connected(self) -> DatabaseClient:
        """DatabaseClient with _pool = None (not connected)."""
        return DatabaseClient(dsn="postgresql://test:test@localhost:5432/test")

    @pytest.fixture
    def mock_conn_for_tx(self, db: DatabaseClient) -> MagicMock:
        """Set up pool.acquire() returning a mock connection with a transaction context manager."""
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[_FakeRecord(id="r1"), _FakeRecord(id="r2")])
        conn.fetchrow = AsyncMock(return_value=_FakeRecord(id="row-uuid"))
        conn.fetchval = AsyncMock(return_value=42)
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        conn.executemany = AsyncMock(return_value=None)

        # conn.transaction() returns an async context manager
        tx_cm = AsyncMock()
        tx_cm.__aenter__ = AsyncMock(return_value=None)
        tx_cm.__aexit__ = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=tx_cm)

        # pool.acquire() returns an async context manager
        acquire_cm = AsyncMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=None)
        db._pool.acquire = MagicMock(return_value=acquire_cm)

        return conn

    @pytest.mark.asyncio
    async def test_transaction_commits_on_success(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify transaction commits (no rollback) when no exception occurs."""
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO test VALUES (1)")

        # __aexit__ should have been called with no exception info
        tx_cm = mock_conn_for_tx.transaction.return_value
        tx_cm.__aexit__.assert_awaited_once()
        args = tx_cm.__aexit__.call_args[0]
        assert args[0] is None  # exc_type is None → commit

    @pytest.mark.asyncio
    async def test_transaction_rolls_back_on_exception(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify transaction rolls back when an exception occurs."""
        with pytest.raises(RuntimeError, match="test error"):
            async with db.transaction() as tx:
                await tx.execute("INSERT INTO test VALUES (1)")
                raise RuntimeError("test error")

        tx_cm = mock_conn_for_tx.transaction.return_value
        tx_cm.__aexit__.assert_awaited_once()
        args = tx_cm.__aexit__.call_args[0]
        assert args[0] is RuntimeError  # exc_type is RuntimeError → rollback

    @pytest.mark.asyncio
    async def test_transaction_proxy_fetch(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.fetch delegates to connection.fetch."""
        async with db.transaction() as tx:
            rows = await tx.fetch("SELECT * FROM test")

        assert len(rows) == 2
        assert rows[0]["id"] == "r1"
        mock_conn_for_tx.fetch.assert_awaited_once_with("SELECT * FROM test")

    @pytest.mark.asyncio
    async def test_transaction_proxy_fetchrow(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.fetchrow delegates to connection.fetchrow."""
        async with db.transaction() as tx:
            row = await tx.fetchrow("SELECT * FROM test WHERE id = $1", "r1")

        assert row is not None
        assert row["id"] == "row-uuid"
        mock_conn_for_tx.fetchrow.assert_awaited_once_with("SELECT * FROM test WHERE id = $1", "r1")

    @pytest.mark.asyncio
    async def test_transaction_proxy_fetchval(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.fetchval delegates to connection.fetchval."""
        async with db.transaction() as tx:
            val = await tx.fetchval("SELECT count(*) FROM test")

        assert val == 42
        mock_conn_for_tx.fetchval.assert_awaited_once_with("SELECT count(*) FROM test")

    @pytest.mark.asyncio
    async def test_transaction_proxy_execute(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.execute delegates to connection.execute."""
        async with db.transaction() as tx:
            status = await tx.execute("INSERT INTO test VALUES (1)")

        assert status == "INSERT 0 1"
        mock_conn_for_tx.execute.assert_awaited_once_with("INSERT INTO test VALUES (1)")

    @pytest.mark.asyncio
    async def test_transaction_proxy_executemany(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.executemany delegates to connection.executemany."""
        params = [(1,), (2,)]
        async with db.transaction() as tx:
            await tx.executemany("INSERT INTO test VALUES ($1)", params)

        mock_conn_for_tx.executemany.assert_awaited_once_with(
            "INSERT INTO test VALUES ($1)", params
        )

    @pytest.mark.asyncio
    async def test_transaction_proxy_fetch_with_timeout(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.fetch passes timeout to connection."""
        async with db.transaction() as tx:
            await tx.fetch("SELECT 1", timeout=5.0)

        mock_conn_for_tx.fetch.assert_awaited_once_with("SELECT 1", timeout=5.0)

    @pytest.mark.asyncio
    async def test_transaction_proxy_fetchrow_with_timeout(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.fetchrow passes timeout to connection."""
        async with db.transaction() as tx:
            await tx.fetchrow("SELECT 1", timeout=5.0)

        mock_conn_for_tx.fetchrow.assert_awaited_once_with("SELECT 1", timeout=5.0)

    @pytest.mark.asyncio
    async def test_transaction_proxy_fetchval_with_timeout(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.fetchval passes timeout to connection."""
        async with db.transaction() as tx:
            await tx.fetchval("SELECT 1", timeout=5.0)

        mock_conn_for_tx.fetchval.assert_awaited_once_with("SELECT 1", timeout=5.0)

    @pytest.mark.asyncio
    async def test_transaction_proxy_execute_with_timeout(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.execute passes timeout to connection."""
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO test VALUES (1)", timeout=5.0)

        mock_conn_for_tx.execute.assert_awaited_once_with(
            "INSERT INTO test VALUES (1)", timeout=5.0
        )

    @pytest.mark.asyncio
    async def test_transaction_proxy_executemany_with_timeout(
        self, db: DatabaseClient, mock_conn_for_tx: MagicMock
    ) -> None:
        """Verify TransactionProxy.executemany passes timeout to connection."""
        params = [(1,)]
        async with db.transaction() as tx:
            await tx.executemany("INSERT INTO test VALUES ($1)", params, timeout=5.0)

        mock_conn_for_tx.executemany.assert_awaited_once_with(
            "INSERT INTO test VALUES ($1)", params, timeout=5.0
        )

    @pytest.mark.asyncio
    async def test_transaction_not_connected_raises(self, db_not_connected: DatabaseClient) -> None:
        """Verify ConnectionError when pool is not initialized."""
        with pytest.raises(ConnectionError, match="not connected"):
            async with db_not_connected.transaction():
                pass  # pragma: no cover
