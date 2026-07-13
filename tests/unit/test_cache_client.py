"""Unit tests for CacheClient (core/cache/__init__.py).

Tests cover:
- Initial state (available=False, no connection attempted)
- Lazy connection (first call triggers connect)
- Successful get/set/delete operations
- Graceful degradation when Redis is unavailable
- Auto-reconnection after connection loss
- Close/cleanup
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.cache import CacheClient


@pytest.fixture
def cache_client() -> CacheClient:
    """Create a CacheClient with test defaults."""
    return CacheClient(host="localhost", port=6379)


@pytest.fixture
def mock_redis() -> MagicMock:
    """Create a mock async Redis client."""
    redis = MagicMock(spec=["ping", "get", "setex", "delete", "aclose"])
    redis.ping = AsyncMock()
    redis.get = AsyncMock()
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.aclose = AsyncMock()
    return redis


class TestCacheClientInitialState:
    """CacheClient should start with no connection attempted."""

    def test_available_is_false_initially(self, cache_client: CacheClient) -> None:
        assert cache_client.available is False

    def test_redis_is_unset_initially(self, cache_client: CacheClient) -> None:
        """Internal _redis should be _UNSET sentinel, not None."""
        from core.cache import _UNSET

        assert cache_client._redis is _UNSET


class TestCacheClientLazyConnection:
    """Connection should only be attempted on first operation."""

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_connect_success(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        mock_redis_cls.return_value = mock_redis
        cache = CacheClient(host="localhost", port=6379)

        client = await cache._connect()

        assert client is mock_redis
        assert cache.available is True
        mock_redis_cls.assert_called_once_with(
            host="localhost",
            port=6379,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            decode_responses=True,
        )
        mock_redis.ping.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_connect_failure(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        mock_redis.ping.side_effect = RedisConnectionError("Connection refused")
        cache = CacheClient(host="localhost", port=6379)

        client = await cache._connect()

        assert client is None
        assert cache.available is False
        assert cache._redis is None  # Reset to None for retry

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_connect_reuses_existing_connection(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        mock_redis_cls.return_value = mock_redis
        cache = CacheClient(host="localhost", port=6379)

        # First call — connects
        client1 = await cache._connect()
        # Second call — reuses
        client2 = await cache._connect()

        assert client1 is client2 is mock_redis
        # Redis constructor should only be called once
        mock_redis_cls.assert_called_once()

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_connect_retries_after_failure(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        cache = CacheClient(host="localhost", port=6379)

        # First call — fails
        mock_redis.ping.side_effect = RedisConnectionError("Connection refused")
        client1 = await cache._connect()
        assert client1 is None
        assert cache._redis is None

        # Second call — succeeds (retry)
        mock_redis.ping.side_effect = None  # Clear side effect
        client2 = await cache._connect()
        assert client2 is mock_redis
        assert cache.available is True
        # Redis constructor should be called twice (first fail, second retry)
        assert mock_redis_cls.call_count == 2

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_connect_timeout(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        from redis.asyncio import TimeoutError as RedisTimeoutError

        mock_redis_cls.return_value = mock_redis
        mock_redis.ping.side_effect = RedisTimeoutError("Timeout")
        cache = CacheClient(host="localhost", port=6379)

        client = await cache._connect()

        assert client is None
        assert cache.available is False

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_connect_oserror(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        mock_redis_cls.return_value = mock_redis
        mock_redis.ping.side_effect = OSError("Network unreachable")
        cache = CacheClient(host="localhost", port=6379)

        client = await cache._connect()

        assert client is None
        assert cache.available is False


class TestCacheClientGet:
    """CacheClient.get() should return values or None on error."""

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_get_hit(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        mock_redis_cls.return_value = mock_redis
        mock_redis.get.return_value = "cached_value"
        cache = CacheClient()

        result = await cache.get("my_key")

        assert result == "cached_value"
        mock_redis.get.assert_awaited_once_with("my_key")

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_get_miss(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        mock_redis_cls.return_value = mock_redis
        mock_redis.get.return_value = None
        cache = CacheClient()

        result = await cache.get("missing_key")

        assert result is None

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_get_returns_none_when_redis_unavailable(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        mock_redis.ping.side_effect = RedisConnectionError("Connection refused")
        cache = CacheClient()

        result = await cache.get("any_key")

        assert result is None

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_get_resets_on_connection_lost(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        cache = CacheClient()

        # First — connect successfully
        await cache._connect()
        assert cache.available is True

        # Then — connection lost during get
        mock_redis.get.side_effect = RedisConnectionError("Connection lost")
        result = await cache.get("key")

        assert result is None
        assert cache.available is False
        assert cache._redis is None  # Reset for retry


class TestCacheClientSet:
    """CacheClient.set() should store values or return False on error."""

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_set_success(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        mock_redis_cls.return_value = mock_redis
        cache = CacheClient()

        result = await cache.set("key", "value")

        assert result is True
        mock_redis.setex.assert_awaited_once_with("key", 3600, "value")

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_set_with_custom_ttl(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        mock_redis_cls.return_value = mock_redis
        cache = CacheClient()

        result = await cache.set("key", "value", ttl=timedelta(minutes=5))

        assert result is True
        mock_redis.setex.assert_awaited_once_with("key", 300, "value")

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_set_returns_false_when_redis_unavailable(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        mock_redis.ping.side_effect = RedisConnectionError("Connection refused")
        cache = CacheClient()

        result = await cache.set("key", "value")

        assert result is False

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_set_resets_on_connection_lost(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        cache = CacheClient()

        # First — connect successfully
        await cache._connect()
        assert cache.available is True

        # Then — connection lost during set
        mock_redis.setex.side_effect = RedisConnectionError("Connection lost")
        result = await cache.set("key", "value")

        assert result is False
        assert cache.available is False
        assert cache._redis is None  # Reset for retry


class TestCacheClientDelete:
    """CacheClient.delete() should remove keys or return False on error."""

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_delete_success(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        mock_redis_cls.return_value = mock_redis
        mock_redis.delete.return_value = 1
        cache = CacheClient()

        result = await cache.delete("key")

        assert result is True
        mock_redis.delete.assert_awaited_once_with("key")

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_delete_missing_key(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        mock_redis_cls.return_value = mock_redis
        mock_redis.delete.return_value = 0
        cache = CacheClient()

        result = await cache.delete("missing_key")

        assert result is False  # 0 → bool(0) → False

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_delete_returns_false_when_redis_unavailable(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        mock_redis.ping.side_effect = RedisConnectionError("Connection refused")
        cache = CacheClient()

        result = await cache.delete("key")

        assert result is False

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_delete_resets_on_connection_lost(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        cache = CacheClient()

        # First — connect successfully
        await cache._connect()
        assert cache.available is True

        # Then — connection lost during delete
        mock_redis.delete.side_effect = RedisConnectionError("Connection lost")
        result = await cache.delete("key")

        assert result is False
        assert cache.available is False
        assert cache._redis is None  # Reset for retry


class TestCacheClientClose:
    """CacheClient.close() should clean up the connection."""

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_close_connected(self, mock_redis_cls: MagicMock, mock_redis: MagicMock) -> None:
        mock_redis_cls.return_value = mock_redis
        cache = CacheClient()

        await cache._connect()  # Establish connection
        assert cache.available is True

        await cache.close()

        assert cache.available is False
        assert cache._redis is None
        mock_redis.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_not_connected(self, cache_client: CacheClient) -> None:
        """Close should be safe when never connected."""
        await cache_client.close()
        assert cache_client.available is False
        assert cache_client._redis is None

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_close_after_failed_connect(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        mock_redis.ping.side_effect = RedisConnectionError("Connection refused")
        cache = CacheClient()

        await cache._connect()  # Fails
        assert cache._redis is None

        await cache.close()  # Should be safe
        assert cache.available is False
        assert cache._redis is None


class TestCacheClientAvailableProperty:
    """The available property should reflect current state."""

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_available_becomes_true_after_connect(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        mock_redis_cls.return_value = mock_redis
        cache = CacheClient()

        assert cache.available is False
        await cache._connect()
        assert cache.available is True

    @pytest.mark.asyncio
    @patch("core.cache.aioredis.Redis")
    async def test_available_becomes_false_after_connection_lost(
        self, mock_redis_cls: MagicMock, mock_redis: MagicMock
    ) -> None:
        from redis.asyncio import ConnectionError as RedisConnectionError

        mock_redis_cls.return_value = mock_redis
        cache = CacheClient()

        await cache._connect()
        assert cache.available is True

        mock_redis.get.side_effect = RedisConnectionError("Lost")
        await cache.get("key")
        assert cache.available is False
