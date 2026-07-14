"""DatabaseClient — asyncpg connection pool.

PostgreSQL is the primary storage for canonical models.
If the database is unavailable, the application must fail fast
rather than silently degrade.

Design:
- Lazy connection (pool created on first use via connect())
- connect() raises on failure — caller must handle
- All query methods (fetch, fetchrow, etc.) raise on error
- close() for graceful shutdown
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import asyncpg

from core.observability import get_logger

logger = get_logger(__name__)

# Connection pool configuration
_POOL_MIN_SIZE: int = 1
_POOL_MAX_SIZE: int = 10
_CONNECT_TIMEOUT: float = 5.0
_COMMAND_TIMEOUT: float = 30.0

# Whitelist of table names allowed for upsert (protection against SQL injection)
_UPSERT_ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "document",
        "document_section",
        "data_source",
        "document_type",
        "organization",
        "jurisdiction",
        "region",
        "topic",
        "rubric",
    }
)


class DatabaseClient:
    """Asyncpg connection pool wrapper.

    Usage::

        db = DatabaseClient(dsn="postgresql://user:pass@localhost:5432/db")
        await db.connect()
        row = await db.fetchrow("SELECT * FROM document WHERE id = $1", doc_id)
        await db.close()
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    @property
    def available(self) -> bool:
        """Whether the pool is currently connected."""
        return self._pool is not None

    async def connect(self) -> asyncpg.Pool:
        """Lazy connection — creates the pool on first call.

        Raises:
            asyncpg.PostgresError: If connection fails.
            OSError: If the database host is unreachable.
            ConnectionError: If the connection is refused.
        """
        if self._pool is not None:
            return self._pool

        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=_POOL_MIN_SIZE,
            max_size=_POOL_MAX_SIZE,
            timeout=_CONNECT_TIMEOUT,
            command_timeout=_COMMAND_TIMEOUT,
        )
        # Verify connection by executing a simple query
        async with self._pool.acquire() as conn:
            await conn.execute("SELECT 1", timeout=_COMMAND_TIMEOUT)
        logger.info("PostgreSQL connected: %s", self._dsn)
        return self._pool

    async def _ensure_connected(self) -> asyncpg.Pool:
        """Ensure pool is connected, raising if not."""
        if self._pool is None:
            raise ConnectionError("DatabaseClient is not connected. Call connect() first.")
        return self._pool

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[asyncpg.Record]:
        """Execute a query and return all rows.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        pool = await self._ensure_connected()
        async with pool.acquire() as conn:
            if timeout is not None:
                return cast("list[asyncpg.Record]", await conn.fetch(query, *args, timeout=timeout))
            return cast("list[asyncpg.Record]", await conn.fetch(query, *args))

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> asyncpg.Record | None:
        """Execute a query and return the first row (or None if no rows).

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        pool = await self._ensure_connected()
        async with pool.acquire() as conn:
            if timeout is not None:
                return await conn.fetchrow(query, *args, timeout=timeout)
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any, timeout: float | None = None) -> Any:
        """Execute a query and return the first column of the first row.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        pool = await self._ensure_connected()
        async with pool.acquire() as conn:
            if timeout is not None:
                return await conn.fetchval(query, *args, timeout=timeout)
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        """Execute a query (INSERT/UPDATE/DELETE) and return the status string.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        pool = await self._ensure_connected()
        async with pool.acquire() as conn:
            if timeout is not None:
                return cast(str, await conn.execute(query, *args, timeout=timeout))
            return cast(str, await conn.execute(query, *args))

    async def upsert(
        self,
        table: str,
        data: dict[str, Any],
        conflict_columns: list[str],
        update_columns: list[str] | None = None,
        returning: str = "id",
    ) -> asyncpg.Record | None:
        """Generic upsert helper.

        Generates::

            INSERT INTO {table} (col1, col2, ...)
            VALUES ($1, $2, ...)
            ON CONFLICT (conflict_col1, conflict_col2)
            DO UPDATE SET col1 = EXCLUDED.col1, col2 = EXCLUDED.col2, ...
            RETURNING {returning}

        Args:
            table: Table name (validated against whitelist).
            data: Column-value mapping.
            conflict_columns: Columns that form the unique constraint.
            update_columns: Columns to update on conflict.
                            If None, updates all columns except conflict_columns.
            returning: Column to return (default: "id").

        Returns:
            Record with the requested column, or None if no row was affected.

        Raises:
            ValueError: If table name is not in the allowed whitelist,
                        or if data/conflict_columns is empty.
        """
        if table not in _UPSERT_ALLOWED_TABLES:
            raise ValueError(
                f"Table '{table}' is not in the upsert whitelist. "
                f"Allowed tables: {sorted(_UPSERT_ALLOWED_TABLES)}"
            )
        if not data:
            raise ValueError("data must not be empty")
        if not conflict_columns:
            raise ValueError("conflict_columns must not be empty")

        columns = list(data.keys())
        values = list(data.values())

        # Determine which columns to update on conflict
        if update_columns is None:
            update_columns = [col for col in columns if col not in conflict_columns]

        # Validate update_columns
        for col in update_columns:
            if col not in data:
                raise ValueError(f"update_column '{col}' not found in data keys: {columns}")

        # Build parameterized SQL
        col_list = ", ".join(columns)
        param_list = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
        conflict_list = ", ".join(conflict_columns)
        set_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)

        query = (
            f"INSERT INTO {table} ({col_list}) "
            f"VALUES ({param_list}) "
            f"ON CONFLICT ({conflict_list}) DO UPDATE SET {set_clause} "
            f"RETURNING {returning}"
        )

        pool = await self._ensure_connected()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *values)

    async def executemany(
        self, query: str, args: list[tuple[Any, ...]], timeout: float | None = None
    ) -> None:
        """Execute the same query with multiple parameter sets.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        pool = await self._ensure_connected()
        async with pool.acquire() as conn:
            if timeout is not None:
                await conn.executemany(query, args, timeout=timeout)
            else:
                await conn.executemany(query, args)

    async def close(self) -> None:
        """Close the connection pool gracefully."""
        if self._pool is not None:
            await self._pool.close()
        self._pool = None

    @staticmethod
    def serialize_jsonb(value: dict[str, Any] | None) -> str | None:
        """Serialize a dict to a JSON string for JSONB columns.

        Uses ``json.dumps`` with ``default=str`` to handle non-serializable
        types (e.g. ``datetime``, ``Decimal``) and ``ensure_ascii=False``
        for Unicode support.

        Args:
            value: Dict to serialize, or None.

        Returns:
            JSON string, or None if input is None/empty.
        """
        if not value:
            return None
        return json.dumps(value, default=str, ensure_ascii=False)

    @staticmethod
    def deserialize_jsonb(value: Any) -> dict[str, Any]:
        """Deserialize a JSONB value from PostgreSQL to a dict.

        Handles three cases:
        - ``None`` → returns ``{}``
        - Already a ``dict`` → returned as-is (asyncpg may auto-deserialize)
        - ``str`` → parsed via ``json.loads``
        - Anything else → returns ``{}``

        Args:
            value: Raw JSONB value from PostgreSQL.

        Returns:
            Dict representation.
        """
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value) if isinstance(value, str) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    async def paginated_fetch(
        self,
        query: str,
        *args: Any,
        limit: int,
        offset: int,
        timeout: float | None = None,
    ) -> list[asyncpg.Record]:
        """Execute a paginated query with LIMIT/OFFSET appended automatically.

        The query should NOT include LIMIT/OFFSET — they are appended as
        positional parameters using the next available ``$N`` placeholders.

        Args:
            query: SQL query without LIMIT/OFFSET.
            *args: Positional parameters for the query.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip.
            timeout: Optional per-query timeout in seconds.

        Returns:
            List of asyncpg.Record objects.

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        paginated_query = f"{query.rstrip(';')} LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}"
        return await self.fetch(paginated_query, *args, limit, offset, timeout=timeout)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[TransactionProxy]:
        """Context manager for transactions.

        Acquires a single connection from the pool and wraps it in a
        TransactionProxy. All operations within the ``async with`` block
        run on the same connection and are committed atomically on success
        or rolled back on exception.

        Usage::

            async with db.transaction() as tx:
                await tx.execute("INSERT INTO ...")
                await tx.execute("UPDATE ...")
            # auto-commit on success, auto-rollback on exception

        Raises:
            asyncpg.PostgresError: On query failure.
            ConnectionError: If not connected.
        """
        pool = await self._ensure_connected()
        async with pool.acquire() as conn, conn.transaction():
            yield TransactionProxy(conn)


class TransactionProxy:
    """Wraps an asyncpg.Connection to provide the same interface as
    DatabaseClient but within a transaction.

    All operations (fetch, fetchrow, fetchval, execute, executemany)
    are delegated to the underlying connection rather than the pool.
    """

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[asyncpg.Record]:
        """Execute a query and return all rows."""
        if timeout is not None:
            return cast(
                "list[asyncpg.Record]", await self._conn.fetch(query, *args, timeout=timeout)
            )
        return cast("list[asyncpg.Record]", await self._conn.fetch(query, *args))

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> asyncpg.Record | None:
        """Execute a query and return the first row (or None if no rows)."""
        if timeout is not None:
            return await self._conn.fetchrow(query, *args, timeout=timeout)
        return await self._conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any, timeout: float | None = None) -> Any:
        """Execute a query and return the first column of the first row."""
        if timeout is not None:
            return await self._conn.fetchval(query, *args, timeout=timeout)
        return await self._conn.fetchval(query, *args)

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        """Execute a query (INSERT/UPDATE/DELETE) and return the status string."""
        if timeout is not None:
            return cast(str, await self._conn.execute(query, *args, timeout=timeout))
        return cast(str, await self._conn.execute(query, *args))

    async def executemany(
        self, query: str, args: list[tuple[Any, ...]], timeout: float | None = None
    ) -> None:
        """Execute the same query with multiple parameter sets."""
        if timeout is not None:
            await self._conn.executemany(query, args, timeout=timeout)
        else:
            await self._conn.executemany(query, args)

    async def upsert(
        self,
        table: str,
        data: dict[str, Any],
        conflict_columns: list[str],
        update_columns: list[str] | None = None,
        returning: str = "*",
    ) -> asyncpg.Record | None:
        """Insert or update a row within the current transaction.

        Delegates to DatabaseClient.upsert() logic but uses the
        underlying connection directly.
        """
        if table not in _UPSERT_ALLOWED_TABLES:
            raise ValueError(
                f"Table '{table}' is not in the upsert whitelist. "
                f"Allowed tables: {sorted(_UPSERT_ALLOWED_TABLES)}"
            )
        if not data:
            raise ValueError("data must not be empty")
        if not conflict_columns:
            raise ValueError("conflict_columns must not be empty")

        columns = list(data.keys())
        values = list(data.values())

        if update_columns is None:
            update_columns = [col for col in columns if col not in conflict_columns]

        for col in update_columns:
            if col not in data:
                raise ValueError(f"update_column '{col}' not found in data keys: {columns}")

        col_list = ", ".join(columns)
        param_list = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
        conflict_list = ", ".join(conflict_columns)
        set_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)

        query = (
            f"INSERT INTO {table} ({col_list}) "
            f"VALUES ({param_list}) "
            f"ON CONFLICT ({conflict_list}) DO UPDATE SET {set_clause} "
            f"RETURNING {returning}"
        )

        return await self._conn.fetchrow(query, *values)


__all__ = [
    "DatabaseClient",
    "TransactionProxy",
]
