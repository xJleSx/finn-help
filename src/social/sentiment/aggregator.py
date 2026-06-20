import logging
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from src.config import personal
from src.db.connection import get_session
from src.db.models import SentimentSignal

logger = logging.getLogger(__name__)


class SocialAggregator:
    def __init__(self) -> None:
        self._sources_cfg = personal.get("social_sources", {})

    def get_ticker_sentiment(self, ticker: str, days: int = 7) -> dict[str, Any]:
        db = get_session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows: list[SentimentSignal] = (
                db.query(SentimentSignal)
                .filter(
                    SentimentSignal.ticker == ticker.upper(),
                    SentimentSignal.created_at >= cutoff,
                )
                .all()
            )

            if not rows:
                return {"score": 0.0, "divergence": 0.0, "source": "social", "count": 0}

            scores = [float(r.composite_score) for r in rows if r.composite_score is not None]
            confs = [float(r.confidence) for r in rows if r.confidence is not None]
            weights = [float(r.source_weight or 0.5) for r in rows]

            if not scores:
                return {"score": 0.0, "divergence": 0.0, "source": "social", "count": 0}

            total_w = sum(weights)
            if total_w > 0:
                weighted = sum(s * w for s, w in zip(scores, weights)) / total_w
            else:
                weighted = mean(scores)
            divergence = (max(scores) - min(scores)) / 2 if len(scores) > 1 else 0.0

            return {
                "score": round(weighted, 3),
                "divergence": round(min(divergence, 1.0), 3),
                "source": "social",
                "count": len(rows),
                "avg_confidence": round(mean(confs), 3) if confs else 0.0,
            }
        finally:
            db.close()

    def get_market_overview(self, days: int = 1) -> list[dict[str, Any]]:
        db = get_session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows: list[SentimentSignal] = (
                db.query(SentimentSignal).filter(SentimentSignal.created_at >= cutoff).all()
            )
            if not rows:
                return []

            by_ticker: dict[str, list[float]] = {}
            for r in rows:
                t = str(r.ticker or "__market__")
                by_ticker.setdefault(t, []).append(float(r.composite_score or 0.0))

            overview = []
            for ticker, scores in sorted(by_ticker.items(), key=lambda x: -len(x[1])):
                overview.append(
                    {
                        "ticker": None if ticker == "__market__" else ticker,
                        "avg_score": round(sum(scores) / len(scores), 3),
                        "volume": len(scores),
                    }
                )
            return overview
        finally:
            db.close()


aggregator = SocialAggregator()
