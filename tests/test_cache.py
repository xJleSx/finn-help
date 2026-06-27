from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.cache import cached, invalidate, make_key


class TestMakeKey:
    def test_consistent_hashing(self):
        k1 = make_key("pfx", "a", b=1)
        k2 = make_key("pfx", "a", b=1)
        assert k1 == k2
        assert k1.startswith("finn:")

    def test_different_args(self):
        k1 = make_key("pfx", "a", b=1)
        k2 = make_key("pfx", "b", b=1)
        assert k1 != k2


class TestCachedDecorator:
    def test_caches_in_memory(self):
        call_count = 0

        @cached(ttl=300, prefix="test")
        def fn(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        assert fn(5) == 10
        assert call_count == 1
        assert fn(5) == 10
        assert call_count == 1  # cached

        assert fn(7) == 14
        assert call_count == 2  # different arg

    def test_uses_redis_when_available(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        call_count = 0

        @cached(ttl=60)
        def compute(v: int) -> int:
            nonlocal call_count
            call_count += 1
            return v + 1

        with patch("src.cache.get_redis", return_value=mock_redis):
            result = compute(3)
            assert result == 4
            assert call_count == 1
            mock_redis.setex.assert_called_once()

    def test_reads_from_redis(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = "42"

        @cached(ttl=60)
        def compute(v: int) -> int:
            return v + 1

        with patch("src.cache.get_redis", return_value=mock_redis):
            result = compute(41)
            assert result == 42

    def test_redis_error_falls_back(self):
        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("timeout")

        call_count = 0

        @cached(ttl=60)
        def compute(v: int) -> int:
            nonlocal call_count
            call_count += 1
            return v

        with patch("src.cache.get_redis", return_value=mock_redis):
            assert compute(1) == 1
            assert call_count == 1

    def test_memory_ttl_expiry(self):
        call_count = 0

        @cached(ttl=0)  # 0 second TTL — will expire immediately
        def fn() -> int:
            nonlocal call_count
            call_count += 1
            return 42

        with patch("src.cache.time") as mock_time:
            mock_time.time.side_effect = [100.0, 100.5, 200.0]
            v1 = fn()
            assert v1 == 42
            v2 = fn()  # second call, TTL=0, time diff >0
            assert v2 == 42
            assert call_count == 2


class TestInvalidate:
    def test_invalidate_memory(self):
        from src.cache import _memory_cache

        _memory_cache["finn:abc"] = (100.0, 1)
        _memory_cache["finn:def"] = (100.0, 2)

        invalidate("abc")
        assert "finn:abc" not in _memory_cache
        assert "finn:def" in _memory_cache

    def test_invalidate_redis_scan(self):
        mock_redis = MagicMock()
        mock_redis.scan.side_effect = [(0, [b"finn:abc"])]

        with patch("src.cache.get_redis", return_value=mock_redis):
            invalidate("abc")
            mock_redis.delete.assert_called_once_with(b"finn:abc")
