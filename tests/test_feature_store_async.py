from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.analysis.feature_store import (
    FEATURE_TYPE_TTL,
    _mem,
    _MemoryCache,
    bump_version,
    clear_stale_async,
    get_cached_async,
    invalidate_async,
    set_cache_async,
)


class TestMemoryCache:
    def test_set_get(self):
        cache = _MemoryCache(maxsize=10)
        cache.set("key1", {"value": 1})
        assert cache.get("key1") == {"value": 1}

    def test_get_missing(self):
        cache = _MemoryCache()
        assert cache.get("nonexistent") is None

    def test_clear_prefix(self):
        cache = _MemoryCache()
        cache.set("abc:1", "a")
        cache.set("abc:2", "b")
        cache.set("xyz:1", "c")
        cache.clear(prefix="abc:")
        assert cache.get("abc:1") is None
        assert cache.get("xyz:1") == "c"

    def test_clear_all(self):
        cache = _MemoryCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.size == 0

    def test_maxsize_eviction(self):
        cache = _MemoryCache(maxsize=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        assert cache.size <= 2


@pytest.mark.asyncio
async def test_get_cached_async_miss():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    result = await get_cached_async(mock_db, "SBER", "technical")
    assert result is None


@pytest.mark.asyncio
async def test_invalidate_async_clears_memory():
    _mem.set("SBER:technical:v1", {"data": 1})
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    await invalidate_async(mock_db, "SBER", "technical")
    assert _mem.get("SBER:technical:v1") is None


def test_bump_version():
    old = bump_version("technical")
    assert old > 1


def test_ttl_values():
    assert FEATURE_TYPE_TTL.get("technical") == 1
    assert FEATURE_TYPE_TTL.get("fundamental") == 3
