"""Cache — Redis-backed with in-memory fallback when Redis is unavailable.

Provides CacheClient with lazy connection, graceful degradation,
and automatic reconnection on the next operation after a failure.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import redis.asyncio as aioredis

from core.observability import get_logger

logger = get_logger(__name__)

# Sentinel value to distinguish "not checked yet" from "connection failed"
_UNSET: Any = object()

# Default TTL for cached items (1 hour)
_DEFAULT_CACHE_TTL: timedelta = timedelta(hours=1)

# Connection timeout in seconds
_CONNECT_TIMEOUT: float = 2.0

# Operation timeout in seconds
_OPERATION_TIMEOUT: float = 2.0


class CacheClient:
    """Redis cache client with graceful degradation.

    If Redis is unavailable at connection time or goes down mid-operation,
    falls back to a no-op cache that logs a warning and returns None for all
    lookups. Automatically retries connection on the next operation.

    Usage::

        cache = CacheClient(host="localhost", port=6379)
        await cache.set("key", "value")
        value = await cache.get("key")  # returns str | None
        await cache.delete("key")
        await cache.close()
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        default_ttl: timedelta = _DEFAULT_CACHE_TTL,
    ) -> None:
        self._host = host
        self._port = port
        self._default_ttl = default_ttl
        self._redis: aioredis.Redis | None = _UNSET
        self._available = False

    @property
    def available(self) -> bool:
        """Whether Redis is currently available."""
        return self._available

    async def _connect(self) -> aioredis.Redis | None:
        """Lazy connection — retries on every call if previously failed.

        Uses _UNSET sentinel to distinguish three states:
        - _UNSET: never tried yet → try to connect
        - None: previous attempt failed → retry
        - Redis instance: connected and healthy → reuse
        """
        if self._redis is not _UNSET and self._redis is not None:
            return self._redis

        # Either _UNSET (first call) or None (previous failure) — try to connect
        try:
            self._redis = aioredis.Redis(
                host=self._host,
                port=self._port,
                socket_connect_timeout=_CONNECT_TIMEOUT,
                socket_timeout=_OPERATION_TIMEOUT,
                decode_responses=True,
            )
            await self._redis.ping()
            self._available = True
            logger.info("Redis connected at %s:%s", self._host, self._port)
            return self._redis
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as exc:
            logger.warning(
                "Redis unavailable at %s:%s — falling back to no-op cache: %s",
                self._host,
                self._port,
                exc,
            )
            self._redis = None
            self._available = False
            return None

    async def get(self, key: str) -> Any | None:
        """Get a value from cache. Returns None on cache miss or Redis error."""
        client = await self._connect()
        if client is None:
            return None
        try:
            return await client.get(key)
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError):
            self._available = False
            self._redis = None  # Reset so _connect() retries next time
            logger.exception("Redis connection lost during get — resetting")
            return None

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> bool:
        """Set a value in cache with optional TTL. Returns False on error."""
        client = await self._connect()
        if client is None:
            return False
        try:
            ttl_seconds = int((ttl or self._default_ttl).total_seconds())
            return await client.setex(key, ttl_seconds, value)
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError):
            self._available = False
            self._redis = None  # Reset so _connect() retries next time
            logger.exception("Redis connection lost during set — resetting")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key from cache. Returns False on error."""
        client = await self._connect()
        if client is None:
            return False
        try:
            return bool(await client.delete(key))
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError):
            self._available = False
            self._redis = None  # Reset so _connect() retries next time
            logger.exception("Redis connection lost during delete — resetting")
            return False

    async def check_health(self) -> bool:
        """Actively check if Redis is reachable by attempting a ping.

        Returns True if Redis responds, False otherwise.
        Also updates ``self._available`` accordingly.
        """
        client = await self._connect()
        return client is not None

    async def close(self) -> None:
        """Close the Redis connection gracefully."""
        if self._redis is not _UNSET and self._redis is not None:
            await self._redis.aclose()
        self._redis = None
        self._available = False


__all__ = [
    "CacheClient",
]
