import logging
from datetime import date, timedelta
from typing import Any, Callable, Optional, cast

from sqlalchemy import delete

from src.db.connection import get_session
from src.db.models import FeatureCache

logger = logging.getLogger(__name__)


class _MemoryCache:
    def __init__(self, maxsize: int = 512):
        self._store: dict[str, Any] = {}
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[Any]:
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self._maxsize:
            self._store.pop(next(iter(self._store)), None)
        self._store[key] = value

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


def _mem_key(ticker: str, feature_type: str) -> str:
    return f"{ticker.upper()}:{feature_type}"


def get_cached(ticker: str, feature_type: str, max_age_days: int = 1) -> Optional[dict[str, Any]]:
    mem_key = _mem_key(ticker, feature_type)
    cached = _mem.get(mem_key)
    if cached is not None:
        return cast(dict[str, Any], cached)
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
        age = (date.today() - row.date).days
        if age > max_age_days:
            return None
        _mem.set(mem_key, row.value_json)
        return cast(dict[str, Any], row.value_json)
    finally:
        db.close()


def set_cache(ticker: str, feature_type: str, value: dict[str, Any]) -> None:
    mem_key = _mem_key(ticker, feature_type)
    _mem.set(mem_key, value)
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
            )
        )
        db.commit()
    except Exception as e:
        logger.warning("Failed to cache feature %s/%s: %s", ticker, feature_type, e)
        db.rollback()
    finally:
        db.close()


def clear_stale(max_age_days: int = 7) -> int:
    db = get_session()
    try:
        cutoff = date.today() - timedelta(days=max_age_days)
        result = db.execute(delete(FeatureCache).where(FeatureCache.date < cutoff))
        db.commit()
        _mem.clear()
        return result.rowcount or 0  # type: ignore[attr-defined]
    finally:
        db.close()


def cached_or_compute(
    ticker: str,
    feature_type: str,
    compute_fn: Callable[[], dict[str, Any]],
    max_age_days: int = 1,
) -> dict[str, Any]:
    cached = get_cached(ticker, feature_type, max_age_days)
    if cached is not None:
        return cached
    result = compute_fn()
    set_cache(ticker, feature_type, result)
    return result


def clear_memory_cache(ticker: Optional[str] = None) -> None:
    if ticker:
        _mem.clear(prefix=f"{ticker.upper()}:")
    else:
        _mem.clear()
