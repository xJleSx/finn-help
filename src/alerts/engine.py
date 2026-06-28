from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from src.analysis.anomaly.detector import AnomalyDetector
from src.analysis.ml.news_impact import NewsImpactModel
from src.config import settings
from src.db.models import Instrument, News, NewsInstrument, Portfolio

logger = logging.getLogger(__name__)


class AlertDeduplicator:
    def __init__(self, hours: int = 24) -> None:
        self._hours = hours
        self._seen: dict[str, datetime] = {}

    def is_duplicate(self, article: News) -> bool:
        key = f"{article.category}:{article.subcategory}:{article.source_name}"
        now = datetime.now(timezone.utc)
        last = self._seen.get(key)
        if last and (now - last).total_seconds() < self._hours * 3600:
            return True
        self._seen[key] = now
        return False

    def reset(self) -> None:
        self._seen.clear()


class AlertTimer:
    def __init__(self, cooldown_minutes: int = 60) -> None:
        self._cooldown = cooldown_minutes
        self._last_sent: dict[str, datetime] = {}

    def can_send(self, ticker: str) -> bool:
        now = datetime.now(timezone.utc)
        last = self._last_sent.get(ticker)
        if last and (now - last).total_seconds() < self._cooldown * 60:
            return False
        self._last_sent[ticker] = now
        return True

    def reset(self) -> None:
        self._last_sent.clear()


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
                alert = self._build_alert(article, ticker, anomaly, impact, in_portfolio)
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

    def _build_alert(
        self, article: News, ticker: str,
        anomaly: dict[str, Any], impact: dict[str, Any],
        in_portfolio: bool,
    ) -> dict[str, Any]:
        anomaly_score = anomaly.get("anomaly_score", 0.0)
        pred_return = impact.get("predicted_return", 0.0)
        impact_conf = impact.get("confidence", 0.0)
        impact_magnitude = min(abs(pred_return) * 20.0, 1.0)

        now = datetime.now(timezone.utc)
        published = article.published_at or now
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        hours_ago = (now - published).total_seconds() / 3600.0
        recency_score = max(0.0, 1.0 - hours_ago / 48.0)

        portfolio_score = 1.0 if in_portfolio else 0.3

        raw_score = (
            anomaly_score * settings.alert_weight_anomaly
            + impact_magnitude * settings.alert_weight_impact
            + portfolio_score * settings.alert_weight_portfolio
            + recency_score * settings.alert_weight_recency
        )

        priority, reason = self._classify(anomaly_score, pred_return, in_portfolio)

        return {
            "news_id": article.id,
            "ticker": ticker,
            "title": article.title or "",
            "category": article.category or "",
            "subcategory": article.subcategory or "",
            "source_name": article.source_name or "",
            "published_at": published.isoformat(),
            "priority": priority,
            "priority_score": round(raw_score, 4),
            "anomaly_score": round(anomaly_score, 4),
            "predicted_return": round(pred_return, 4),
            "impact_confidence": round(impact_conf, 4),
            "in_portfolio": in_portfolio,
            "reason": reason,
        }

    def _classify(
        self, anomaly_score: float, pred_return: float, in_portfolio: bool,
    ) -> tuple[str, str]:
        reasons: list[str] = []
        if anomaly_score >= 0.5:
            reasons.append(f"anomaly detected ({anomaly_score:.2f})")
        if abs(pred_return) >= settings.alert_min_impact_abs:
            direction = "positive" if pred_return > 0 else "negative"
            reasons.append(f"predicted {direction} return of {pred_return:.2%}")
        if in_portfolio:
            reasons.append("in your portfolio")

        abs_return = abs(pred_return)
        if anomaly_score >= settings.alert_critical_threshold or (
            in_portfolio and abs_return >= 0.02 and anomaly_score >= 0.5
        ):
            return "CRITICAL", "; ".join(reasons) if reasons else "high anomaly score"
        if anomaly_score >= settings.alert_high_threshold or (
            abs_return >= 0.01 and in_portfolio
        ):
            return "HIGH", "; ".join(reasons) if reasons else "elevated anomaly score"
        if anomaly_score >= settings.alert_medium_threshold or abs_return >= 0.005:
            return "MEDIUM", "; ".join(reasons) if reasons else "moderate signal"
        return "LOW", "; ".join(reasons) if reasons else "low priority"

    def reset(self) -> None:
        self.deduplicator.reset()
        self.timer.reset()
