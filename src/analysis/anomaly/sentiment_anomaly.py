from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest

from src.analysis.anomaly.features import sentiment_features_per_day
from src.config import settings


class SentimentAnomalyDetector:
    def __init__(self, ticker: str = "") -> None:
        self.ticker = ticker
        self._model: IsolationForest | None = None
        self._trained = False
        self._feature_cols: list[str] = []

    def train(self, db: Any, ticker: str | None = None) -> dict[str, Any]:
        t = ticker or self.ticker
        if not t:
            return {"trained": False, "reason": "no ticker"}
        df = sentiment_features_per_day(db, t)
        if df.empty or len(df) < settings.ml_anomaly_min_samples:
            return {"trained": False, "reason": "insufficient data"}
        self._feature_cols = [
            c
            for c in df.columns
            if c not in ("sentiment_mean", "article_count")
        ]
        x = df[self._feature_cols].values
        self._model = IsolationForest(
            n_estimators=100,
            contamination=settings.ml_anomaly_sentiment_contamination,
            random_state=42,
        )
        self._model.fit(x)
        self._trained = True
        return {"trained": True, "samples": len(x), "features": len(self._feature_cols)}

    def predict(self, features: dict[str, float]) -> float:
        if self._model is None:
            return 0.0
        vec = np.array(
            [[features.get(c, 0.0) for c in self._feature_cols]], dtype=np.float32
        )
        score = self._model.score_samples(vec)[0]
        anomaly_score = float(np.clip(-score / 10.0, 0.0, 1.0))
        return anomaly_score

    def predict_article(self, db: Any, news_article: Any) -> float:
        published = news_article.published_at
        if published is None:
            published = datetime.now(timezone.utc)
        features = self._build_single_day_features(db, published)
        return self.predict(features)

    def _build_single_day_features(self, db: Any, day: datetime) -> dict[str, float]:
        from datetime import timedelta

        from sqlalchemy import func, select

        from src.db.models import Instrument, News, NewsInstrument

        result: dict[str, float] = {}
        windows = [int(w) for w in settings.ml_anomaly_window_sizes.split(",")]
        for w in windows:
            start = day - timedelta(days=w)
            row = (
                db.execute(
                    select(func.avg(News.sentiment_score).label("avg"))
                    .join(NewsInstrument, NewsInstrument.news_id == News.id)
                    .join(Instrument, Instrument.id == NewsInstrument.instrument_id)
                    .where(News.published_at >= start)
                    .where(News.published_at <= day)
                    .where(Instrument.ticker == self.ticker)
                ).scalar()
                or 0.0
            )
            result[f"sent_ma_{w}d"] = float(row)
            result[f"sent_std_{w}d"] = 0.0
        result["sent_change_1d"] = 0.0
        result["sent_change_3d"] = 0.0
        return result

    @property
    def trained(self) -> bool:
        return self._trained
