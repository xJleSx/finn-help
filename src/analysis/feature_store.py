import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete

from src.db.connection import get_session
from src.db.models import FeatureCache

logger = logging.getLogger(__name__)


def get_cached(ticker: str, feature_type: str, max_age_days: int = 1) -> dict | None:
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
        return row.value_json
    finally:
        db.close()


def set_cache(ticker: str, feature_type: str, value: dict) -> None:
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
        return result.rowcount or 0
    finally:
        db.close()


def cached_or_compute(
    ticker: str,
    feature_type: str,
    compute_fn,
    max_age_days: int = 1,
) -> dict[str, Any]:
    cached = get_cached(ticker, feature_type, max_age_days)
    if cached is not None:
        return cached
    result = compute_fn()
    set_cache(ticker, feature_type, result)
    return result
