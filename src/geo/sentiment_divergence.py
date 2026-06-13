import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import News

logger = logging.getLogger(__name__)


class SentimentDivergenceDetector:
    def detect(self, db: Optional[Session] = None, news_list: Optional[list[dict]] = None) -> dict:
        if db:
            cutoff = datetime.utcnow() - timedelta(days=3)
            recent_news = db.query(News).filter(News.created_at >= cutoff).all()
            scores = [n.sentiment_score for n in recent_news if n.sentiment_score is not None]
        elif news_list:
            scores = [n.get("sentiment_score", 0) for n in news_list if n.get("sentiment_score") is not None]
        else:
            return {"divergence": 0.0, "signals": ["нет данных"], "sources_count": 0}

        if not scores:
            return {"divergence": 0.0, "signals": ["нет новостей для анализа"], "sources_count": 0}

        variance = self._variance(scores)
        mean_sentiment = sum(scores) / len(scores)

        divergence = min(variance * 2, 1.0)

        result = {
            "divergence": round(divergence, 2),
            "mean_sentiment": round(mean_sentiment, 2),
            "sources_count": len(scores),
            "signals": [],
        }

        if divergence > 0.6:
            result["signals"].append("сильное расхождение тональности новостей — противоречивые сигналы")
        elif divergence > 0.3:
            result["signals"].append("умеренное расхождение тональности")

        if mean_sentiment > 0.3 and divergence > 0.5:
            result["signals"].append("⚠️ новости позитивны, но мнения сильно расходятся")

        return result

    def _variance(self, values: list[float]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)
