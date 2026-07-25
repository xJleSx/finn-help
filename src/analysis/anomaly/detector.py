from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.analysis.anomaly.autoencoder import AutoencoderAnomalyDetector
from src.analysis.anomaly.sentiment_anomaly import SentimentAnomalyDetector
from src.analysis.anomaly.source_anomaly import SourceAnomalyDetector
from src.analysis.anomaly.topic_anomaly import TopicAnomalyDetector
from src.analysis.anomaly.volume_anomaly import VolumeAnomalyDetector
from src.config import settings

logger = logging.getLogger(__name__)


class AnomalyDetector:
    def __init__(self, ticker: str = "") -> None:
        self.ticker = ticker
        self.volume = VolumeAnomalyDetector(ticker)
        self.sentiment = SentimentAnomalyDetector(ticker)
        self.source = SourceAnomalyDetector()
        self.topic = TopicAnomalyDetector()
        self.autoencoder = AutoencoderAnomalyDetector()

    def train_all(self, db: Session, cutoff_date: datetime | None = None) -> dict[str, Any]:
        results: dict[str, Any] = {}
        results["volume"] = self.volume.train(db, self.ticker, cutoff_date=cutoff_date)
        results["sentiment"] = self.sentiment.train(db, self.ticker, cutoff_date=cutoff_date)
        results["source"] = self.source.train(db)
        results["topic"] = self.topic.train(db)
        results["autoencoder"] = self.autoencoder.train(db, self.ticker)
        return results

    def predict_article(self, db: Session, news_article: Any) -> dict[str, Any]:
        weights = {
            "volume": settings.ml_anomaly_weight_volume,
            "sentiment": settings.ml_anomaly_weight_sentiment,
            "source": settings.ml_anomaly_weight_source,
            "topic": settings.ml_anomaly_weight_topic,
            "autoencoder": settings.ml_anomaly_weight_autoencoder,
        }

        # Use expanding window: retrain with data only up to the article's date
        # to prevent future leakage
        article_date = getattr(news_article, "published_at", datetime.now(timezone.utc))
        self.train_all(db, cutoff_date=article_date)

        scores: dict[str, float] = {}
        scores["volume"] = self.volume.predict_article(db, news_article) if self.volume.trained else 0.0
        scores["sentiment"] = self.sentiment.predict_article(db, news_article) if self.sentiment.trained else 0.0
        scores["source"] = self.source.predict_article(news_article) if self.source.trained else 0.0
        scores["topic"] = self.topic.predict_article(news_article) if self.topic.trained else 0.0
        scores["autoencoder"] = self.autoencoder.predict_article(db, news_article) if self.autoencoder.trained else 0.0
        total_weight = sum(weights.get(k, 0.0) for k in scores if scores[k] > 0)
        weighted = 0.0 if total_weight == 0 else sum(scores[k] * weights.get(k, 0.0) for k in scores) / total_weight
        is_anomaly = weighted >= 0.5
        return {
            "anomaly_score": round(weighted, 4),
            "is_anomaly": is_anomaly,
            "details": scores,
        }
