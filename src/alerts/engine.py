from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from src.analysis.anomaly.detector import AnomalyDetector
from src.analysis.ml.news_impact import NewsImpactModel
from src.alerts.deduplicator import AlertDeduplicator, AlertTimer
from src.alerts.scorer import build_alert, classify_priority
from src.config import settings
from src.db.models import Instrument, News, NewsInstrument, Portfolio

logger = logging.getLogger(__name__)


class AlertEngine:
    def __init__(self) -> None:
        self.anomaly_detector = AnomalyDetector()
        self._anomaly_trained = False
        self._trained_tickers: set[str] = set()
        self.deduplicator = AlertDeduplicator(settings.alert_dedup_hours)
        self.timer = AlertTimer(settings.alert_cooldown_minutes)

    def train_anomaly(self, db: Any) -> dict[str, Any]:
        result = self.anomaly_detector.train_all(db)
        self._anomaly_trained = any(
            v.get("trained", False) for v in result.values()
        )
        return result

    def train_impact(self, db: Any, tickers: list[str] | None = None) -> dict[str, Any]:
        if tickers is None:
            rows = db.execute(select(Instrument.ticker)).all()
            tickers = [r[0] for r in rows]
        results: dict[str, Any] = {}
        for ticker in tickers:
            model = NewsImpactModel(ticker)
            result = model.train(db)
            if result.get("trained"):
                self._trained_tickers.add(ticker)
            results[ticker] = result
        return results

    def process_articles(
        self, db: Any, articles: list[News], portfolio_tickers: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if portfolio_tickers is None:
            portfolio_tickers = set()

        candidates: list[dict[str, Any]] = []
        for article in articles:
            if self.deduplicator.is_duplicate(article):
                continue

            tickers = self._article_tickers(db, article)
            if not tickers:
                continue

            anomaly = (
                self.anomaly_detector.predict_article(db, article)
                if self._anomaly_trained
                else {"anomaly_score": 0.0, "is_anomaly": False, "details": {}}
            )

            for ticker in tickers:
                if not self.timer.can_send(ticker):
                    continue

                impact = self._predict_impact(db, article, ticker)
                in_portfolio = ticker in portfolio_tickers
                alert = build_alert(article, ticker, anomaly, impact, in_portfolio)
                candidates.append(alert)

        candidates.sort(key=lambda a: a["priority_score"], reverse=True)
        return candidates[: settings.alert_max_alerts_per_run]

    def process_portfolio_articles(
        self, db: Any, articles: list[News], user_id: int = 0,
    ) -> list[dict[str, Any]]:
        rows = (
            db.execute(
                select(Instrument.ticker)
                .join(Portfolio, Portfolio.instrument_id == Instrument.id)
                .where(Portfolio.user_id == user_id)
            )
            .all()
        )
        portfolio_tickers = {r[0] for r in rows}
        return self.process_articles(db, articles, portfolio_tickers)

    def _article_tickers(self, db: Any, article: News) -> list[str]:
        rows = (
            db.execute(
                select(Instrument.ticker)
                .join(NewsInstrument, NewsInstrument.instrument_id == Instrument.id)
                .where(NewsInstrument.news_id == article.id)
            )
            .all()
        )
        return [r[0] for r in rows]

    def _predict_impact(self, db: Any, article: News, ticker: str) -> dict[str, Any]:
        if ticker not in self._trained_tickers:
            return {"predicted_return": 0.0, "confidence": 0.0, "model_loaded": False}
        model = NewsImpactModel(ticker)
        return model.predict(db, article, horizon_days=1)

    def reset(self) -> None:
        self.deduplicator.reset()
        self.timer.reset()
