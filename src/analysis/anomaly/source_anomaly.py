from __future__ import annotations

from typing import Any

from src.analysis.anomaly.features import source_frequencies


class SourceAnomalyDetector:
    def __init__(self) -> None:
        self._freqs: dict[str, dict[str, float]] = {}
        self._trained = False

    def train(self, db: Any) -> dict[str, Any]:
        self._freqs = source_frequencies(db)
        self._trained = True
        return {"trained": True, "sources": len(self._freqs)}

    def predict_article(self, news_article: Any) -> float:
        source = getattr(news_article, "source_name", None) or "unknown"
        category = getattr(news_article, "category", None) or "UNCLASSIFIED"

        if not self._trained or source not in self._freqs:
            return 0.0

        cat_ratio = self._freqs[source].get(category, 0.0)
        if cat_ratio <= 0.1:
            return 0.8
        if cat_ratio <= 0.3:
            return 0.4
        if cat_ratio >= 5.0:
            return 0.0
        return 0.0

    @property
    def trained(self) -> bool:
        return self._trained
