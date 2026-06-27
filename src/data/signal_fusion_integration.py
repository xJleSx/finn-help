"""Integration with Signal Fusion Engine.

Adds news/sector/company risk signals to the main fusion engine.
Updates portfolio allocator with new risk components.
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# New signal weights for fusion
NEWS_RISK_COMPONENT_WEIGHT = 0.15  # 15% of total signal weight


class SignalFusionIntegration:
    """Integrates news/sector/company risk signals into Signal Fusion Engine."""

    def __init__(
        self,
        geo_engine: Any,
        sector_engine: Any,
        company_aggregator: Any,
        event_detector: Any,
    ):
        """Initialize integration.

        Args:
            geo_engine: GeopoliticalRiskEngine instance
            sector_engine: SectorImpactEngine instance
            company_aggregator: CompanyRiskAggregator instance
            event_detector: EventDetector instance
        """
        self.geo_engine = geo_engine
        self.sector_engine = sector_engine
        self.company_aggregator = company_aggregator
        self.event_detector = event_detector

    def generate_news_risk_signal(
        self, instrument: Any, db_session: Any
    ) -> dict[str, Any]:
        """Generate news-based risk signal for an instrument.

        Args:
            instrument: Instrument ORM object
            db_session: Database session

        Returns:
            Signal dict with confidence and components
        """
        # Get company risk assessment
        company_risk = self.company_aggregator.calculate_company_risk(
            instrument, db_session
        )

        # Get geopolitical context
        geo_risk = self.geo_engine.calculate_daily_geopolitical_risk(db_session)

        # Extract relevant news articles
        from src.db.models import News, NewsInstrument

        recent_news = db_session.query(News).join(
            NewsInstrument, NewsInstrument.news_id == News.id
        ).filter(
            NewsInstrument.instrument_id == instrument.id,
            News.is_relevant,
        ).limit(10).all()

        # Aggregate sentiments
        sentiments = [n.sentiment for n in recent_news if n.sentiment]
        dominant_sentiment = "neutral"
        if sentiments:
            positive = sum(1 for s in sentiments if s == "positive")
            negative = sum(1 for s in sentiments if s == "negative")
            if positive > negative:
                dominant_sentiment = "positive"
            elif negative > positive:
                dominant_sentiment = "negative"

        return {
            "ticker": instrument.ticker,
            "signal_type": "news_risk",
            "risk_score": company_risk["risk_score"],
            "confidence": min(1.0, len(recent_news) / 5),  # More articles = higher confidence
            "components": {
                "sector_risk": company_risk["components"]["sector_risk"],
                "geopolitical_risk": company_risk["components"]["geopolitical_risk"],
                "macro_risk": company_risk["components"]["macro_risk"],
                "company_risk": company_risk["components"]["company_specific_risk"],
                "geo_overall": geo_risk["risk_score"],
            },
            "sentiment": dominant_sentiment,
            "recent_articles": len(recent_news),
            "generated_at": datetime.utcnow().isoformat(),
        }

    def generate_sector_risk_signal(
        self, sector: str, db_session: Any
    ) -> dict[str, Any]:
        """Generate sector-level risk signal.

        Args:
            sector: Sector name
            db_session: Database session

        Returns:
            Signal dict
        """
        from src.db.models import SectorRiskHistory

        risk_history = db_session.query(SectorRiskHistory).filter(
            SectorRiskHistory.sector == sector,
            SectorRiskHistory.date == datetime.utcnow().date(),
        ).first()

        if not risk_history:
            return {
                "sector": sector,
                "signal_type": "sector_risk",
                "risk_score": 0.0,
                "confidence": 0.0,
            }

        return {
            "sector": sector,
            "signal_type": "sector_risk",
            "risk_score": risk_history.risk_score,
            "confidence": min(1.0, risk_history.article_count / 5),
            "article_count": risk_history.article_count,
            "components": risk_history.components_json,
            "generated_at": datetime.utcnow().isoformat(),
        }

    def generate_geopolitical_signal(self, db_session: Any) -> dict[str, Any]:
        """Generate geopolitical risk signal.

        Args:
            db_session: Database session

        Returns:
            Signal dict
        """
        geo_risk = self.geo_engine.calculate_daily_geopolitical_risk(db_session)

        return {
            "signal_type": "geopolitical_risk",
            "risk_score": geo_risk["risk_score"],
            "alert_level": self.geo_engine.get_risk_alert_level(geo_risk["risk_score"]),
            "confidence": geo_risk["source_diversity_score"],
            "subcategories": geo_risk["subcategories"],
            "article_count": geo_risk["total_article_count"],
            "generated_at": datetime.utcnow().isoformat(),
        }

    def adjust_portfolio_weights_for_risk(
        self, portfolio_weights: dict[str, float], db_session: Any
    ) -> dict[str, float]:
        """Adjust portfolio allocation based on news/sector/company risks.

        Args:
            portfolio_weights: Current portfolio weights {ticker: weight}
            db_session: Database session

        Returns:
            Adjusted weights {ticker: new_weight}
        """
        from src.db.models import Instrument

        adjusted = portfolio_weights.copy()

        for ticker, weight in portfolio_weights.items():
            instrument = db_session.query(Instrument).filter_by(ticker=ticker).first()
            if not instrument:
                continue

            # Get company risk signal
            signal = self.generate_news_risk_signal(instrument, db_session)
            risk_score = signal["risk_score"]

            # Reduce weight by risk proportion
            # High risk (8-10) → reduce by 80-100%
            # Medium risk (5-7) → reduce by 50-70%
            # Low risk (0-4) → reduce by 0-40%
            risk_reduction = min(risk_score / 10, 1.0)

            adjusted[ticker] = weight * (1 - risk_reduction * NEWS_RISK_COMPONENT_WEIGHT)

        # Renormalize to sum to 1.0
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: v / total for k, v in adjusted.items()}

        return adjusted

    def generate_risk_alerts(self, db_session: Any) -> list[dict[str, Any]]:
        """Generate actionable risk alerts.

        Args:
            db_session: Database session

        Returns:
            List of alerts sorted by urgency
        """
        alerts = []

        # High geopolitical risk alert
        geo_risk = self.geo_engine.calculate_daily_geopolitical_risk(db_session)
        if geo_risk["risk_score"] > 6.5:
            alerts.append({
                "type": "geopolitical_escalation",
                "severity": "HIGH" if geo_risk["risk_score"] > 8 else "MEDIUM",
                "risk_score": geo_risk["risk_score"],
                "message": f"Geopolitical risk at {geo_risk['risk_score']:.1f}/10",
                "action": "Review exposure to high-risk sectors",
                "timestamp": datetime.utcnow().isoformat(),
            })

        # Sector-level alerts
        from src.db.models import SectorRiskHistory

        high_risk_sectors = db_session.query(SectorRiskHistory).filter(
            SectorRiskHistory.date == datetime.utcnow().date(),
            SectorRiskHistory.risk_score > 6.5,
        ).order_by(SectorRiskHistory.risk_score.desc()).limit(5).all()

        for sector_risk in high_risk_sectors:
            alerts.append({
                "type": "sector_risk_elevated",
                "severity": "HIGH" if sector_risk.risk_score > 8 else "MEDIUM",
                "sector": sector_risk.sector,
                "risk_score": sector_risk.risk_score,
                "article_count": sector_risk.article_count,
                "message": f"Sector {sector_risk.sector} risk at {sector_risk.risk_score:.1f}/10",
                "action": f"Reduce exposure to {sector_risk.sector}",
                "timestamp": datetime.utcnow().isoformat(),
            })

        # Sentiment divergence alerts (uncertainty signals)
        from src.data.event_detector import SentimentDivergenceDetector

        detector = SentimentDivergenceDetector()
        divergences = detector.find_all_divergences(db_session, min_articles=3)

        for div in divergences[:3]:  # Top 3 divergences
            ticker = div.get("ticker") or div.get("sector")
            alerts.append({
                "type": "sentiment_divergence",
                "severity": "INFO",
                "target": ticker,
                "divergence": div["divergence"],
                "consensus": div["consensus"],
                "message": f"Mixed sentiment detected in {ticker} - uncertainty signal",
                "action": "Monitor for volatility increase",
                "timestamp": datetime.utcnow().isoformat(),
            })

        # Sort by severity and score
        severity_order = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
        alerts.sort(
            key=lambda x: (
                severity_order.get(x["severity"], 3),
                -(x.get("risk_score", 0) + x.get("divergence", 0)),
            )
        )

        return alerts

    def update_signal_metadata(self, signal: dict[str, Any], db_session: Any) -> dict[str, Any]:
        """Add news-based metadata to an existing signal.

        Args:
            signal: Existing signal dict
            db_session: Database session

        Returns:
            Enhanced signal dict
        """
        # Add news context if available
        ticker = signal.get("ticker")
        if not ticker:
            return signal

        from src.db.models import Instrument

        instrument = db_session.query(Instrument).filter_by(ticker=ticker).first()
        if not instrument:
            return signal

        # Add company risk components
        news_signal = self.generate_news_risk_signal(instrument, db_session)

        signal["news_context"] = {
            "risk_score": news_signal["risk_score"],
            "confidence": news_signal["confidence"],
            "sentiment": news_signal["sentiment"],
            "recent_articles": news_signal["recent_articles"],
            "components": news_signal["components"],
        }

        # Adjust confidence based on news
        if "confidence" in signal:
            # Boost confidence if news supports technical signal
            if (signal.get("action") == "BUY" and news_signal["sentiment"] == "positive") or \
               (signal.get("action") == "SELL" and news_signal["sentiment"] == "negative"):
                signal["confidence"] *= 1.2
            elif (signal.get("action") == "BUY" and news_signal["sentiment"] == "negative") or \
                 (signal.get("action") == "SELL" and news_signal["sentiment"] == "positive"):
                signal["confidence"] *= 0.8

            signal["confidence"] = min(signal["confidence"], 1.0)

        return signal
