from __future__ import annotations

from typing import Any

from src.analysis.anomaly.features import topic_frequencies
from src.config import settings


class TopicAnomalyDetector:
    def __init__(self) -> None:
        self._freqs: dict[str, dict[tuple[str, str], int]] = {}
        self._trained = False

    def train(self, db: Any) -> dict[str, Any]:
        self._freqs = topic_frequencies(db)
        self._trained = True
        tickers = len(self._freqs)
        total_topics = sum(len(ts) for ts in self._freqs.values())
        return {"trained": True, "tickers": tickers, "topics": total_topics}

    def predict_article(self, news_article: Any) -> float:
        ticker = getattr(news_article, "ticker", "") or ""
        category = getattr(news_article, "category", None) or "UNCLASSIFIED"
        subcategory = getattr(news_article, "subcategory", None) or "GENERAL"
        topic = (category, subcategory)

        if not self._trained or ticker not in self._freqs:
            return 0.0
        ticker_topics = self._freqs[ticker]
        total = sum(ticker_topics.values())
        if total < settings.ml_anomaly_source_min_freq:
            return 0.0
        topic_count = ticker_topics.get(topic, 0)
        ratio = topic_count / max(total, 1)
        if topic_count == 0:
            return 0.7
        if ratio < 0.01:
            return 0.5
        if ratio < 0.05:
            return 0.2
        return 0.0

    @property
    def trained(self) -> bool:
        return self._trained
