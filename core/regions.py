"""RegionResolver — resolves region text to UUID with caching.

Used by ODLService to convert a user-provided region name (e.g. 'Московская область')
into a region UUID for Qdrant filtering. Results are cached in Redis with 24h TTL.
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.cache import CacheClient
    from core.persistence.repository import ReferenceRepository

_CACHE_TTL = timedelta(hours=24)


class RegionResolver:
    """Resolves region text to region UUID with caching.

    Uses ReferenceRepository.search_region_id() for trigram full-text search.
    Results are cached in Redis (cache-aside pattern) for 24 hours.

    If cache is unavailable, falls through to DB lookup.
    If DB is unavailable, returns None (graceful degradation).
    """

    def __init__(
        self,
        ref_repo: ReferenceRepository | None,
        cache: CacheClient | None = None,
    ) -> None:
        self._ref_repo = ref_repo
        self._cache = cache

    async def resolve(self, region_name: str) -> tuple[str, float] | None:
        """Resolve region name to (UUID, similarity_score).

        Checks cache first, then falls through to DB trigram search.
        Successful DB results are cached for 24 hours.

        Args:
            region_name: Region name to resolve (e.g. 'Московская область').

        Returns:
            Tuple of (region_uuid, similarity_score) or None if not found.
        """
        if not region_name or not region_name.strip():
            return None

        cache_key = f"region:{region_name.lower().strip()}"

        # 1. Check cache
        cached = await self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # 2. DB lookup
        if self._ref_repo is None:
            return None

        result = await self._ref_repo.search_region_id(region_name)
        if result is None:
            return None

        region_id, score = result

        # 3. Cache the result
        await self._set_in_cache(cache_key, region_id, score)

        return region_id, score

    async def _get_from_cache(self, cache_key: str) -> tuple[str, float] | None:
        """Try to get region resolution from cache."""
        if self._cache is None:
            return None
        with suppress(Exception):
            cached = await self._cache.get(cache_key)
            if cached is not None:
                data = json.loads(cached)
                return str(data["uuid"]), float(data["score"])
        return None

    async def _set_in_cache(self, cache_key: str, region_id: str, score: float) -> None:
        """Set region resolution in cache."""
        if self._cache is None:
            return
        with suppress(Exception):
            await self._cache.set(
                cache_key,
                json.dumps({"uuid": region_id, "score": score}),
                ttl=_CACHE_TTL,
            )
