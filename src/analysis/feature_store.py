from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional, cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_async_session, get_session
from src.db.models import FeatureCache

logger = logging.getLogger(__name__)

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


def _get_redis() -> Any:
    global _redis_instance
    if _redis_instance is None:
        try:
            import redis as redis_mod

            _redis_instance = redis_mod.Redis(
                host="localhost", port=6379, db=1, decode_responses=True,
                socket_connect_timeout=2, socket_timeout=2,
            )
            _redis_instance.ping()
        except Exception:
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
    if row.ttl_hours is not None:
        if row.created_at and (datetime.now(timezone.utc).replace(tzinfo=None) - row.created_at).total_seconds() > row.ttl_hours * 3600:
            return True
    age = (date.today() - row.date).days
    if age > max_age_days:
        return True
    return False


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
        return cast(dict[str, Any], cached)

    r = _get_redis()
    if r:
        try:
            data = r.get(_redis_key(ticker, feature_type))
            if data is not None:
                parsed = json.loads(data)
                _mem.set(mem_key, parsed)
                return cast(dict[str, Any], parsed)
        except Exception:
            pass

    db = get_session()
    try:
        row = (
            db.query(FeatureCache)
            .filter_by(ticker=ticker.upper(), feature_type=feature_type)
            .order_by(FeatureCache.date.desc())
            .first()
        )
        if not row:
            return None
        if _is_stale(row, max_age, version):
            return None
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
        except Exception:
            pass

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
        except Exception:
            pass

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
        except Exception:
            pass

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
        except Exception:
            pass

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
        except Exception:
            pass

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
        return result.rowcount or 0
    finally:
        db.close()


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
        by_type = (
            db.query(FeatureCache.feature_type, func.count(FeatureCache.id))
            .group_by(FeatureCache.feature_type)
            .all()
        )
        return {
            "memory_entries": _mem.size,
            "db_entries": total,
            "by_type": {row[0]: row[1] for row in by_type},
            "redis_available": _get_redis() is not None,
        }
    finally:
        db.close()
