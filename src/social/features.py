import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.db.connection import get_session
from src.db.models import FeatureCache, SentimentSignal

logger = logging.getLogger(__name__)


def compute_social_features(ticker: str) -> dict[str, Any]:
    db = get_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        rows: list[SentimentSignal] = (
            db.query(SentimentSignal)
            .filter(
                SentimentSignal.ticker == ticker.upper(),
                SentimentSignal.created_at >= cutoff,
            )
            .order_by(SentimentSignal.created_at)
            .all()
        )

        if not rows:
            return {
                "social_volume_7d": 0,
                "social_volume_30d": 0,
                "social_avg_score_7d": 0.0,
                "social_avg_score_30d": 0.0,
                "social_bullish_ratio_7d": 0.0,
                "social_confidence_7d": 0.0,
            }

        now = datetime.now(timezone.utc)
        cutoff_7d = now - timedelta(days=7)
        recent_7d = [r for r in rows if r.created_at >= cutoff_7d]
        recent_30d = rows

        def avg_score(posts: list[SentimentSignal]) -> float:
            scores = [float(r.composite_score) for r in posts if r.composite_score is not None]
            return sum(scores) / len(scores) if scores else 0.0

        def bullish_ratio(posts: list[SentimentSignal]) -> float:
            if not posts:
                return 0.0
            bullish = sum(1 for r in posts if r.composite_score is not None and float(r.composite_score) > 0)
            return bullish / len(posts)

        def avg_confidence(posts: list[SentimentSignal]) -> float:
            confs = [float(r.confidence) for r in posts if r.confidence is not None]
            return sum(confs) / len(confs) if confs else 0.0

        features = {
            "social_volume_7d": len(recent_7d),
            "social_volume_30d": len(recent_30d),
            "social_avg_score_7d": round(avg_score(recent_7d), 4),
            "social_avg_score_30d": round(avg_score(recent_30d), 4),
            "social_bullish_ratio_7d": round(bullish_ratio(recent_7d), 4),
            "social_confidence_7d": round(avg_confidence(recent_7d), 4),
        }

        _cache_features(ticker, features)
        return features
    finally:
        db.close()


def _cache_features(ticker: str, features: dict[str, Any]) -> None:
    db = get_session()
    try:
        today = date.today()
        existing = db.query(FeatureCache).filter_by(ticker=ticker, feature_type="social_sentiment", date=today).first()
        if existing:
            existing.value_json = features  # type: ignore[assignment]
        else:
            cached = FeatureCache(
                ticker=ticker,
                feature_type="social_sentiment",
                date=today,
                value_json=features,
            )
            db.add(cached)
        db.commit()
    except Exception as e:
        logger.warning("Failed to cache social features for %s: %s", ticker, e)
    finally:
        db.close()
