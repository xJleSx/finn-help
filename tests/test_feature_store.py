from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analysis.feature_store import (
    _MemoryCache,
    _mem_key,
    cached_or_compute,
    clear_memory_cache,
    clear_stale,
    get_cached,
    set_cache,
)


class TestMemoryCache:
    def test_set_get(self):
        c = _MemoryCache(maxsize=10)
        c.set("a", 1)
        assert c.get("a") == 1

    def test_get_missing(self):
        c = _MemoryCache()
        assert c.get("missing") is None

    def test_eviction(self):
        c = _MemoryCache(maxsize=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        assert c.size <= 2

    def test_clear_all(self):
        c = _MemoryCache()
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.size == 0

    def test_clear_prefix(self):
        c = _MemoryCache()
        c.set("foo:1", 1)
        c.set("foo:2", 2)
        c.set("bar:1", 3)
        c.clear(prefix="foo:")
        assert c.get("foo:1") is None
        assert c.get("bar:1") == 3


class TestMemKey:
    def test_uppercases_ticker(self):
        assert _mem_key("sber", "atr") == "SBER:atr"


class TestGetCached:
    def test_returns_memory_hit(self):
        with patch("src.analysis.feature_store._mem") as mock_mem:
            mock_mem.get.return_value = {"cached": True}
            result = get_cached("SBER", "atr")
            assert result == {"cached": True}

    def test_returns_none_when_miss(self):
        with (
            patch("src.analysis.feature_store._mem") as mock_mem,
            patch("src.analysis.feature_store.get_session") as mock_get_session,
        ):
            mock_mem.get.return_value = None
            mock_db = MagicMock()
            mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
            mock_get_session.return_value = mock_db

            result = get_cached("SBER", "atr")
            assert result is None
            mock_db.close.assert_called_once()

    def test_returns_stale(self):
        from datetime import date, timedelta

        with (
            patch("src.analysis.feature_store._mem") as mock_mem,
            patch("src.analysis.feature_store.get_session") as mock_get_session,
        ):
            mock_mem.get.return_value = None
            mock_db = MagicMock()
            row = MagicMock()
            row.date = date.today() - timedelta(days=2)
            row.value_json = {"old": True}
            mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = row
            mock_get_session.return_value = mock_db

            result = get_cached("SBER", "atr", max_age_days=1)
            assert result is None  # stale
            mock_db.close.assert_called_once()

    def test_returns_fresh(self):
        from datetime import date

        with (
            patch("src.analysis.feature_store._mem") as mock_mem,
            patch("src.analysis.feature_store.get_session") as mock_get_session,
        ):
            mock_mem.get.return_value = None
            mock_db = MagicMock()
            row = MagicMock()
            row.date = date.today()
            row.value_json = {"fresh": True}
            mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = row
            mock_get_session.return_value = mock_db

            result = get_cached("SBER", "atr")
            assert result == {"fresh": True}
            mock_mem.set.assert_called_once()


class TestSetCache:
    def test_success(self):
        with patch("src.analysis.feature_store.get_session") as mock_get_session:
            mock_db = MagicMock()
            mock_get_session.return_value = mock_db

            set_cache("SBER", "atr", {"v": 1})
            mock_db.execute.assert_called_once()
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()
            mock_db.close.assert_called_once()

    def test_exception_rollback(self):
        with patch("src.analysis.feature_store.get_session") as mock_get_session:
            mock_db = MagicMock()
            mock_db.execute.side_effect = Exception("DB error")
            mock_get_session.return_value = mock_db

            set_cache("SBER", "atr", {"v": 1})
            mock_db.rollback.assert_called_once()
            mock_db.close.assert_called_once()


class TestClearStale:
    def test_deletes_old(self):
        with patch("src.analysis.feature_store.get_session") as mock_get_session:
            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.rowcount = 3
            mock_db.execute.return_value = mock_result
            mock_get_session.return_value = mock_db

            count = clear_stale(max_age_days=7)
            assert count == 3
            mock_db.commit.assert_called_once()
            mock_db.close.assert_called_once()


class TestCachedOrCompute:
    def test_returns_cached(self):
        with patch("src.analysis.feature_store.get_cached") as mock_get:
            mock_get.return_value = {"from_cache": True}
            result = cached_or_compute("SBER", "atr", lambda: {"computed": True})
            assert result == {"from_cache": True}

    def test_computes_and_caches(self):
        with (
            patch("src.analysis.feature_store.get_cached") as mock_get,
            patch("src.analysis.feature_store.set_cache") as mock_set,
        ):
            mock_get.return_value = None
            result = cached_or_compute("SBER", "atr", lambda: {"computed": True})
            assert result == {"computed": True}
            mock_set.assert_called_once()


class TestClearMemoryCache:
    def test_clear_ticker(self):
        from src.analysis.feature_store import _mem

        _mem.set("SBER:atr", 1)
        _mem.set("SBER:vol", 2)
        _mem.set("GAZP:atr", 3)

        clear_memory_cache(ticker="SBER")
        assert _mem.get("SBER:atr") is None
        assert _mem.get("GAZP:atr") == 3

    def test_clear_all(self):
        from src.analysis.feature_store import _mem

        _mem.set("a", 1)
        _mem.set("b", 2)
        clear_memory_cache()
        assert _mem.size == 0
