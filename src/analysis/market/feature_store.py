from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence, cast

from prometheus_client import Counter, Gauge
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_session
from src.db.models import FeatureCache

logger = logging.getLogger(__name__)

CACHE_HITS = Counter("feature_cache_hits_total", "Feature cache hits", ["tier"])
CACHE_MISSES = Counter("feature_cache_misses_total", "Feature cache misses", ["feature_type"])
CACHE_ENTRIES = Gauge("feature_cache_entries", "Feature cache entries", ["tier"])

FEATURE_TYPE_TTL: dict[str, int] = {
    "technical": 1,
    "fundamental": 3,
    "ml_prediction": 1,
    "sentiment": 1,
    "geo_risk": 1,
    "macro": 1,
    "trends": 1,
    "sector_impact": 2,
    "company_profile": 7,
    "news_cluster": 1,
}

FEATURE_TYPE_VERSION: dict[str, int] = {
    "technical": 1,
    "fundamental": 1,
    "ml_prediction": 2,
    "sentiment": 1,
    "geo_risk": 1,
    "macro": 1,
    "trends": 1,
    "sector_impact": 1,
    "company_profile": 1,
    "news_cluster": 1,
}


class _MemoryCache:
    def __init__(self, maxsize: int = 1024):
        self._store: dict[str, tuple[float, Any]] = {}
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is not None:
            return entry[1]
        return None

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self._maxsize:
            self._store.pop(next(iter(self._store)), None)
        self._store[key] = (time.time(), value)

    def clear(self, prefix: Optional[str] = None) -> None:
        if prefix:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
        else:
            self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


_mem = _MemoryCache()

_redis_instance: Any = None
_redis_pool: Any = None


def _get_redis() -> Any:
    global _redis_instance, _redis_pool
    if _redis_instance is None:
        try:
            import redis as redis_mod
            from redis import ConnectionPool

            from src.config import settings

            url = settings.redis_url or "redis://localhost:6379/0"
            _redis_pool = ConnectionPool.from_url(
                url,
                db=1,
                max_connections=settings.redis_max_connections,
                socket_connect_timeout=settings.redis_socket_connect_timeout,
                socket_timeout=settings.redis_socket_timeout,
                decode_responses=True,
            )
            _redis_instance = redis_mod.Redis(connection_pool=_redis_pool)
            _redis_instance.ping()
        except Exception:
            logger.exception("Unhandled exception")
            _redis_instance = False
    return _redis_instance if _redis_instance else None


def _mem_key(ticker: str, feature_type: str, version: int = 1) -> str:
    return f"{ticker.upper()}:{feature_type}:v{version}"


def _redis_key(ticker: str, feature_type: str) -> str:
    return f"finn:feat:{ticker.upper()}:{feature_type}"


def _ttl_for(feature_type: str) -> int:
    return FEATURE_TYPE_TTL.get(feature_type, 1)


def _version_for(feature_type: str) -> int:
    return FEATURE_TYPE_VERSION.get(feature_type, 1)


def _is_stale(row: FeatureCache, max_age_days: int, version: int) -> bool:
    if row.version != version:
        return True
    if row.ttl_hours is not None and row.created_at:
        age = (datetime.now(timezone.utc).replace(tzinfo=None) - row.created_at).total_seconds()
        if age > row.ttl_hours * 3600:
            return True
    age = (date.today() - row.date).days
    return age > max_age_days


def _update_cache_gauges() -> None:
    CACHE_ENTRIES.labels(tier="memory").set(_mem.size)
    r = _get_redis()
    if r:
        try:
            dbsize = r.dbsize()
            CACHE_ENTRIES.labels(tier="redis").set(dbsize)
        except Exception:
            CACHE_ENTRIES.labels(tier="redis").set(0)


def get_cached(
    ticker: str,
    feature_type: str,
    max_age_days: int | None = None,
) -> Optional[dict[str, Any]]:
    version = _version_for(feature_type)
    max_age = max_age_days if max_age_days is not None else _ttl_for(feature_type)

    mem_key = _mem_key(ticker, feature_type, version)
    cached = _mem.get(mem_key)
    if cached is not None:
        CACHE_HITS.labels(tier="memory").inc()
        return cast(dict[str, Any], cached)

    r = _get_redis()
    if r:
        try:
            data = r.get(_redis_key(ticker, feature_type))
            if data is not None:
                parsed = json.loads(data)
                _mem.set(mem_key, parsed)
                CACHE_HITS.labels(tier="redis").inc()
                return cast(dict[str, Any], parsed)
        except Exception as e:
            logger.debug("Redis get failed for %s/%s: %s", ticker, feature_type, e)

    db = get_session()
    try:
        row = db.query(FeatureCache).filter_by(ticker=ticker.upper(), feature_type=feature_type).order_by(FeatureCache.date.desc()).first()
        if not row:
            CACHE_MISSES.labels(feature_type=feature_type).inc()
            return None
        if _is_stale(row, max_age, version):
            CACHE_MISSES.labels(feature_type=feature_type).inc()
            return None
        CACHE_HITS.labels(tier="database").inc()
        _mem.set(mem_key, row.value_json)
        return cast(dict[str, Any], row.value_json)
    finally:
        db.close()


async def get_cached_async(
    db: AsyncSession,
    ticker: str,
    feature_type: str,
    max_age_days: int | None = None,
) -> Optional[dict[str, Any]]:
    version = _version_for(feature_type)
    max_age = max_age_days if max_age_days is not None else _ttl_for(feature_type)

    mem_key = _mem_key(ticker, feature_type, version)
    cached = _mem.get(mem_key)
    if cached is not None:
        return cast(dict[str, Any], cached)

    r = _get_redis()
    if r:
        try:
            data = r.get(_redis_key(ticker, feature_type))
            if data is not None:
                parsed = json.loads(data)
                _mem.set(mem_key, parsed)
                return cast(dict[str, Any], parsed)
        except Exception as e:
            logger.debug("Redis get failed for %s/%s: %s", ticker, feature_type, e)

    result = await db.execute(
        select(FeatureCache)
        .where(
            FeatureCache.ticker == ticker.upper(),
            FeatureCache.feature_type == feature_type,
        )
        .order_by(FeatureCache.date.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    if _is_stale(row, max_age, version):
        return None
    _mem.set(mem_key, row.value_json)
    return cast(dict[str, Any], row.value_json)


def set_cache(
    ticker: str,
    feature_type: str,
    value: dict[str, Any],
    ttl_hours: int | None = None,
) -> None:
    version = _version_for(feature_type)
    mem_key = _mem_key(ticker, feature_type, version)
    _mem.set(mem_key, value)

    r = _get_redis()
    if r:
        try:
            ttl_sec = (ttl_hours or _ttl_for(feature_type)) * 3600
            r.setex(_redis_key(ticker, feature_type), ttl_sec, json.dumps(value, default=str))
        except Exception as e:
            logger.debug("Redis set failed for %s/%s: %s", ticker, feature_type, e)

    db = get_session()
    try:
        db.execute(
            delete(FeatureCache).where(
                FeatureCache.ticker == ticker.upper(),
                FeatureCache.feature_type == feature_type,
            )
        )
        db.add(
            FeatureCache(
                ticker=ticker.upper(),
                feature_type=feature_type,
                date=date.today(),
                value_json=value,
                version=version,
                ttl_hours=ttl_hours,
            )
        )
        db.commit()
    except Exception as e:
        logger.warning("Failed to cache feature %s/%s: %s", ticker, feature_type, e)
        db.rollback()
    finally:
        db.close()


async def set_cache_async(
    db: AsyncSession,
    ticker: str,
    feature_type: str,
    value: dict[str, Any],
    ttl_hours: int | None = None,
) -> None:
    version = _version_for(feature_type)
    mem_key = _mem_key(ticker, feature_type, version)
    _mem.set(mem_key, value)

    r = _get_redis()
    if r:
        try:
            ttl_sec = (ttl_hours or _ttl_for(feature_type)) * 3600
            r.setex(_redis_key(ticker, feature_type), ttl_sec, json.dumps(value, default=str))
        except Exception as e:
            logger.debug("Redis set failed for %s/%s: %s", ticker, feature_type, e)

    try:
        await db.execute(
            delete(FeatureCache).where(
                FeatureCache.ticker == ticker.upper(),
                FeatureCache.feature_type == feature_type,
            )
        )
        db.add(
            FeatureCache(
                ticker=ticker.upper(),
                feature_type=feature_type,
                date=date.today(),
                value_json=value,
                version=version,
                ttl_hours=ttl_hours,
            )
        )
        await db.commit()
    except Exception as e:
        logger.warning("Failed to cache feature %s/%s: %s", ticker, feature_type, e)
        await db.rollback()


def invalidate(ticker: str, feature_type: str | None = None) -> None:
    ticker_up = ticker.upper()
    if feature_type:
        _mem.clear(prefix=_mem_key(ticker_up, feature_type))
    else:
        _mem.clear(prefix=f"{ticker_up}:")

    r = _get_redis()
    if r:
        try:
            if feature_type:
                r.delete(_redis_key(ticker_up, feature_type))
            else:
                for key in r.scan_iter(f"finn:feat:{ticker_up}:*"):
                    r.delete(key)
        except Exception as e:
            logger.debug("Redis delete failed for %s: %s", ticker, e)

    db = get_session()
    try:
        q = delete(FeatureCache).where(FeatureCache.ticker == ticker_up)
        if feature_type:
            q = q.where(FeatureCache.feature_type == feature_type)
        db.execute(q)
        db.commit()
    except Exception as e:
        logger.warning("Failed to invalidate cache for %s: %s", ticker, e)
        db.rollback()
    finally:
        db.close()


async def invalidate_async(db: AsyncSession, ticker: str, feature_type: str | None = None) -> None:
    ticker_up = ticker.upper()
    if feature_type:
        _mem.clear(prefix=_mem_key(ticker_up, feature_type))
    else:
        _mem.clear(prefix=f"{ticker_up}:")

    r = _get_redis()
    if r:
        try:
            if feature_type:
                r.delete(_redis_key(ticker_up, feature_type))
            else:
                for key in r.scan_iter(f"finn:feat:{ticker_up}:*"):
                    r.delete(key)
        except Exception as e:
            logger.debug("Redis delete failed for %s: %s", ticker, e)

    try:
        q = delete(FeatureCache).where(FeatureCache.ticker == ticker_up)
        if feature_type:
            q = q.where(FeatureCache.feature_type == feature_type)
        await db.execute(q)
        await db.commit()
    except Exception as e:
        logger.warning("Failed to invalidate cache for %s: %s", ticker, e)
        await db.rollback()


def clear_stale(max_age_days: int = 7) -> int:
    db = get_session()
    try:
        cutoff = date.today() - timedelta(days=max_age_days)
        result = db.execute(delete(FeatureCache).where(FeatureCache.date < cutoff))
        db.commit()
        _mem.clear()
        removed = result.rowcount or 0
        if removed:
            logger.info("Cleared %d stale feature cache entries (>=%d days old)", removed, max_age_days)
        return removed
    finally:
        db.close()


async def clear_stale_async(db: AsyncSession | None = None, max_age_days: int = 7) -> int:
    if db is None:
        from src.db.connection import get_async_session as _get_async_session
        async with _get_async_session() as session:
            return await _clear_stale_async_impl(session, max_age_days)
    return await _clear_stale_async_impl(db, max_age_days)


async def _clear_stale_async_impl(db: AsyncSession, max_age_days: int) -> int:
    cutoff = date.today() - timedelta(days=max_age_days)
    result = await db.execute(delete(FeatureCache).where(FeatureCache.date < cutoff))
    await db.commit()
    _mem.clear()
    removed = result.rowcount or 0
    if removed:
        logger.info("Cleared %d stale feature cache entries async (>=%d days old)", removed, max_age_days)
    return removed


def cached_or_compute(
    ticker: str,
    feature_type: str,
    compute_fn: Callable[[], dict[str, Any]],
    max_age_days: int | None = None,
    ttl_hours: int | None = None,
) -> dict[str, Any]:
    cached = get_cached(ticker, feature_type, max_age_days)
    if cached is not None:
        return cached
    result = compute_fn()
    set_cache(ticker, feature_type, result, ttl_hours=ttl_hours)
    return result


def get_batch(
    tickers: Sequence[str],
    feature_type: str,
    max_age_days: int | None = None,
) -> dict[str, Optional[dict[str, Any]]]:
    result: dict[str, Optional[dict[str, Any]]] = {}
    for ticker in tickers:
        result[ticker] = get_cached(ticker, feature_type, max_age_days)
    return result


async def get_batch_async(
    db: AsyncSession,
    tickers: Sequence[str],
    feature_type: str,
    max_age_days: int | None = None,
) -> dict[str, Optional[dict[str, Any]]]:
    result: dict[str, Optional[dict[str, Any]]] = {}
    for ticker in tickers:
        result[ticker] = await get_cached_async(db, ticker, feature_type, max_age_days)
    return result


def set_batch(
    items: Sequence[tuple[str, str, dict[str, Any]]],
    ttl_hours: int | None = None,
) -> None:
    for ticker, feature_type, value in items:
        set_cache(ticker, feature_type, value, ttl_hours=ttl_hours)


async def set_batch_async(
    db: AsyncSession,
    items: Sequence[tuple[str, str, dict[str, Any]]],
    ttl_hours: int | None = None,
) -> None:
    for ticker, feature_type, value in items:
        await set_cache_async(db, ticker, feature_type, value, ttl_hours=ttl_hours)


def list_feature_types() -> dict[str, int]:
    db = get_session()
    try:
        rows = db.query(FeatureCache.feature_type, func.count(FeatureCache.id)).group_by(FeatureCache.feature_type).all()
        return {row[0]: row[1] for row in rows}
    finally:
        db.close()


def clear_memory_cache(ticker: Optional[str] = None) -> None:
    if ticker:
        _mem.clear(prefix=f"{ticker.upper()}:")
    else:
        _mem.clear()


def bump_version(feature_type: str) -> int:
    current = FEATURE_TYPE_VERSION.get(feature_type, 1)
    FEATURE_TYPE_VERSION[feature_type] = current + 1
    new_version = current + 1
    logger.info("Bumped feature version for %s to v%d", feature_type, new_version)
    return new_version


def get_stats() -> dict[str, Any]:
    db = get_session()
    try:
        total = db.query(FeatureCache).count()
        by_type = db.query(FeatureCache.feature_type, func.count(FeatureCache.id)).group_by(FeatureCache.feature_type).all()
        return {
            "memory_entries": _mem.size,
            "db_entries": total,
            "by_type": {row[0]: row[1] for row in by_type},
            "redis_available": _get_redis() is not None,
        }
    finally:
        db.close()
