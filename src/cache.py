import hashlib
import json
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_redis = None
_memory_cache: dict[str, tuple[float, Any]] = {}


def get_redis():
    global _redis
    if _redis is None:
        try:
            import redis as redis_mod

            _redis = redis_mod.Redis(
                host="localhost", port=6379, db=0, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
            )
            _redis.ping()
            logger.info("Redis connected at localhost:6379")
        except Exception:
            logger.warning("Redis unavailable, using in-memory fallback")
            _redis = False
    return _redis if _redis else None


def make_key(prefix: str, *args, **kwargs) -> str:
    raw = f"{prefix}:{json.dumps(args, sort_keys=True, default=str)}:{json.dumps(kwargs, sort_keys=True, default=str)}"
    return f"finn:{hashlib.md5(raw.encode()).hexdigest()}"


def cached(
    ttl: int = 300,
    prefix: Optional[str] = None,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            key = make_key(prefix or func.__name__, *args, **kwargs)
            r = get_redis()
            if r:
                try:
                    data = r.get(key)
                    if data is not None:
                        return json.loads(data)
                except Exception:
                    pass
            else:
                entry = _memory_cache.get(key)
                if entry and time.time() - entry[0] < ttl:
                    return entry[1]

            result = func(*args, **kwargs)

            if r:
                try:
                    r.setex(key, ttl, json.dumps(result, default=str))
                except Exception:
                    pass
            else:
                _memory_cache[key] = (time.time(), result)

            return result

        return wrapper

    return decorator


def invalidate(pattern: str):
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
        except Exception:
            pass
    keys_to_delete = [k for k in _memory_cache if k.startswith(key.replace("*", ""))]
    for k in keys_to_delete:
        _memory_cache.pop(k, None)
