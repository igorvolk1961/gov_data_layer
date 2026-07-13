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

from typing import Any, cast

import asyncpg

from core.observability import get_logger

logger = get_logger(__name__)

# Connection pool configuration
_POOL_MIN_SIZE: int = 1
_POOL_MAX_SIZE: int = 10
_CONNECT_TIMEOUT: float = 5.0
_COMMAND_TIMEOUT: float = 30.0


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


__all__ = [
    "DatabaseClient",
]
