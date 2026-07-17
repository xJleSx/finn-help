import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.analysis.feature_store import set_cache
from src.db.connection import get_session
from src.db.models import SentimentSignal

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
            features = {
                "social_volume_7d": 0,
                "social_volume_30d": 0,
                "social_avg_score_7d": 0.0,
                "social_avg_score_30d": 0.0,
                "social_bullish_ratio_7d": 0.0,
                "social_confidence_7d": 0.0,
            }
            set_cache(ticker, "social_sentiment", features)
            return features

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

        set_cache(ticker, "social_sentiment", features)
        return features
    finally:
        db.close()
