from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable

import redis as redis_mod
from redis import ConnectionPool

from src.config import settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_memory_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _get_pool() -> ConnectionPool | None:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                try:
                    url = settings.redis_url or "redis://localhost:6379/0"
                    _pool = ConnectionPool.from_url(
                        url,
                        max_connections=settings.redis_max_connections,
                        socket_connect_timeout=settings.redis_socket_connect_timeout,
                        socket_timeout=settings.redis_socket_timeout,
                        decode_responses=True,
                    )
                    r = redis_mod.Redis(connection_pool=_pool)
                    r.ping()
                    logger.info("Redis connected: %s", url)
                except Exception as exc:
                    logger.warning("Redis unavailable (%s), using in-memory fallback", exc)
                    _pool = False
    return _pool if _pool else None


def get_redis() -> Any:
    pool = _get_pool()
    if pool is None:
        return None
    try:
        return redis_mod.Redis(connection_pool=pool)
    except Exception as exc:
        logger.warning("Failed to get Redis connection from pool: %s", exc)
        return None


def make_key(prefix: str, *args: Any, **kwargs: Any) -> str:
    raw = f"{prefix}:{json.dumps(args, sort_keys=True, default=str)}:{json.dumps(kwargs, sort_keys=True, default=str)}"
    return f"finn:{hashlib.md5(raw.encode()).hexdigest()}"


def cached(
    ttl: int = 300,
    prefix: str | None = None,
) -> Callable[..., Any]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = make_key(prefix or func.__name__, *args, **kwargs)
            r = get_redis()
            if r:
                try:
                    data = r.get(key)
                    if data is not None:
                        return json.loads(data)
                except Exception as exc:
                    logger.debug("Redis get failed: %s", exc)
            else:
                with _lock:
                    entry = _memory_cache.get(key)
                    if entry and time.time() - entry[0] < ttl:
                        return entry[1]

            result = func(*args, **kwargs)

            if r:
                try:
                    r.setex(key, ttl, json.dumps(result, default=str))
                except Exception as exc:
                    logger.debug("Redis set failed: %s", exc)
            else:
                with _lock:
                    _memory_cache[key] = (time.time(), result)

            return result

        return wrapper

    return decorator


def invalidate(pattern: str) -> None:
    key = f"finn:{pattern}"
    r = get_redis()
    if r:
        try:
            cursor = 0
            while True:
                cursor, keys = r.scan(cursor, match=key, count=100)
                if keys:
                    r.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.debug("Redis invalidate failed: %s", exc)
    with _lock:
        keys_to_delete = [k for k in _memory_cache if k.startswith(key.replace("*", ""))]
        for k in keys_to_delete:
            _memory_cache.pop(k, None)


def close_redis() -> None:
    global _pool
    with _lock:
        if _pool and _pool is not False:
            try:
                _pool.disconnect()
                logger.info("Redis connection pool closed")
            except Exception as exc:
                logger.warning("Failed to close Redis pool: %s", exc)
        _pool = None
        _memory_cache.clear()
