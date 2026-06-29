"""News and Risk Dashboards API endpoints.

Provides data for frontend visualization:
- News dashboard (categories, timeline, top stories)
- Sector risk heatmap
- Company risk decomposition
- Geopolitical risk gauge
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


class DashboardDataProvider:
    """Provides aggregated data for dashboards."""

    def __init__(self):
        """Initialize provider."""
        pass

    def get_news_dashboard_data(
        self, db_session: Any, days: int = 7
    ) -> dict[str, Any]:
        """Get data for news dashboard.

        Args:
            db_session: Database session
            days: Time window to analyze

        Returns:
            Dashboard data dict
        """
        from src.db.models import News, NewsEvent

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Get news events
        events = db_session.query(NewsEvent).filter(
            NewsEvent.created_at >= cutoff
        ).order_by(NewsEvent.created_at.desc()).limit(50).all()

        # Categorize
        by_category = {}
        for event in events:
            cat = event.category or "UNCLASSIFIED"
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append({
                "id": event.id,
                "title": event.title,
                "summary": event.summary,
                "category": event.category,
                "subcategory": event.subcategory,
                "impact": event.impact_score,
                "sentiment": event.sentiment,
                "article_count": event.article_count,
                "published": event.published_at.isoformat() if event.published_at else None,
            })

        # Get top news by impact
        all_articles = db_session.query(News).filter(
            News.created_at >= cutoff,
            News.is_relevant,
        ).order_by(News.impact_score.desc()).limit(20).all()

        top_news = []
        for article in all_articles:
            top_news.append({
                "id": article.id,
                "title": article.title,
                "source": article.source_name,
                "impact": article.impact_score,
                "sentiment": article.sentiment,
                "published": article.published_at.isoformat() if article.published_at else None,
            })

        # Statistics
        total_articles = db_session.query(News).filter(
            News.created_at >= cutoff
        ).count()

        relevant_articles = db_session.query(News).filter(
            News.created_at >= cutoff,
            News.is_relevant,
        ).count()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "period_days": days,
            "statistics": {
                "total_articles": total_articles,
                "relevant_articles": relevant_articles,
                "events": len(events),
                "categories": list(by_category.keys()),
            },
            "categories": by_category,
            "top_news": top_news,
        }

    def get_sector_risk_heatmap(self, db_session: Any) -> dict[str, Any]:
        """Get sector risk heatmap data.

        Args:
            db_session: Database session

        Returns:
            Heatmap data {sector: risk_score}
        """
        from src.db.models import Instrument, SectorRiskHistory

        today = datetime.now(timezone.utc).date()

        # Get all sectors
        sectors = db_session.query(Instrument.sector).distinct().filter(
            Instrument.sector.isnot(None)
        ).all()

        heatmap = {}
        for (sector,) in sectors:
            risk = db_session.query(SectorRiskHistory).filter(
                SectorRiskHistory.sector == sector,
                SectorRiskHistory.date == today,
            ).first()

            risk_score = risk.risk_score if risk else 0.0

            heatmap[sector] = {
                "risk_score": risk_score,
                "color": self._get_risk_color(risk_score),
                "article_count": risk.article_count if risk else 0,
                "level": self._get_risk_level(risk_score),
            }

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": today.isoformat(),
            "heatmap": heatmap,
        }

    def get_company_risk_decomposition(
        self, ticker: str, db_session: Any
    ) -> dict[str, Any]:
        """Get risk component breakdown for a company.

        Args:
            ticker: Instrument ticker
            db_session: Database session

        Returns:
            Risk decomposition data
        """
        from src.db.models import CompanyRiskHistory, Instrument

        instrument = db_session.query(Instrument).filter_by(ticker=ticker).first()
        if not instrument:
            return {"error": f"Instrument {ticker} not found"}

        today = datetime.now(timezone.utc).date()

        risk = db_session.query(CompanyRiskHistory).filter(
            CompanyRiskHistory.instrument_id == instrument.id,
            CompanyRiskHistory.date == today,
        ).first()

        if not risk:
            return {
                "ticker": ticker,
                "date": today.isoformat(),
                "total_risk": 0.0,
                "components": {
                    "sector_risk": 0.0,
                    "geopolitical_risk": 0.0,
                    "macro_risk": 0.0,
                    "company_specific_risk": 0.0,
                },
            }

        return {
            "ticker": ticker,
            "sector": instrument.sector,
            "date": today.isoformat(),
            "total_risk": risk.risk_score,
            "components": {
                "sector_risk": risk.sector_risk or 0.0,
                "geopolitical_risk": risk.geopolitical_risk or 0.0,
                "macro_risk": risk.macro_risk or 0.0,
                "company_specific_risk": risk.company_specific_risk or 0.0,
            },
            "weights": {
                "sector_risk": 0.30,
                "geopolitical_risk": 0.30,
                "macro_risk": 0.20,
                "company_specific_risk": 0.20,
            },
        }

    def get_geopolitical_risk_gauge(self, db_session: Any) -> dict[str, Any]:
        """Get geopolitical risk gauge with breakdown.

        Args:
            db_session: Database session

        Returns:
            Gauge data with subcategories
        """
        from src.db.models import GeopoliticalRiskHistory

        today = datetime.now(timezone.utc).date()

        geo_risk = db_session.query(GeopoliticalRiskHistory).filter(
            GeopoliticalRiskHistory.date == today
        ).first()

        if not geo_risk:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "date": today.isoformat(),
                "total_risk": 0.0,
                "alert_level": "low",
                "subcategories": {
                    "sanctions": 0.0,
                    "conflict": 0.0,
                    "trade_war": 0.0,
                    "diplomacy": 0.0,
                },
            }

        alert_level = "low"
        if geo_risk.risk_score > 3:
            alert_level = "medium"
        if geo_risk.risk_score > 5:
            alert_level = "high"
        if geo_risk.risk_score > 7:
            alert_level = "critical"

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": today.isoformat(),
            "total_risk": geo_risk.risk_score,
            "alert_level": alert_level,
            "article_count": geo_risk.article_count or 0,
            "unique_sources": geo_risk.sources_json.get("unique_sources", 0) if geo_risk.sources_json else 0,
            "subcategories": {
                "sanctions": {
                    "risk_score": geo_risk.sanctions_score or 0.0,
                    "weight": 0.35,
                },
                "conflict": {
                    "risk_score": geo_risk.conflict_score or 0.0,
                    "weight": 0.30,
                },
                "trade_war": {
                    "risk_score": geo_risk.trade_war_score or 0.0,
                    "weight": 0.20,
                },
                "diplomacy": {
                    "risk_score": geo_risk.diplomacy_score or 0.0,
                    "weight": 0.15,
                },
            },
        }

    def get_risk_trends(
        self, target: str, target_type: str, db_session: Any, days: int = 30
    ) -> dict[str, Any]:
        """Get risk score trends over time.

        Args:
            target: Sector name or ticker
            target_type: "sector" or "company"
            db_session: Database session
            days: Number of days to analyze

        Returns:
            Trend data
        """
        from src.db.models import CompanyRiskHistory, Instrument, SectorRiskHistory

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        history = []

        if target_type == "sector":
            data = db_session.query(SectorRiskHistory).filter(
                SectorRiskHistory.sector == target,
                SectorRiskHistory.date >= cutoff.date(),
            ).order_by(SectorRiskHistory.date).all()

            history = [
                {"date": d.date.isoformat(), "risk": d.risk_score}
                for d in data
            ]

        elif target_type == "company":
            instrument = db_session.query(Instrument).filter_by(ticker=target).first()
            if instrument:
                data = db_session.query(CompanyRiskHistory).filter(
                    CompanyRiskHistory.instrument_id == instrument.id,
                    CompanyRiskHistory.date >= cutoff.date(),
                ).order_by(CompanyRiskHistory.date).all()

                history = [
                    {"date": d.date.isoformat(), "risk": d.risk_score}
                    for d in data
                ]

        if not history:
            return {"error": f"No data found for {target}"}

        scores = [h["risk"] for h in history]
        current = scores[-1] if scores else 0.0
        average = sum(scores) / len(scores) if scores else 0.0

        trend = "up" if len(scores) > 1 and scores[-1] > scores[0] else "down"

        return {
            "target": target,
            "target_type": target_type,
            "period_days": days,
            "current_risk": current,
            "average_risk": average,
            "max_risk": max(scores) if scores else 0.0,
            "min_risk": min(scores) if scores else 0.0,
            "trend": trend,
            "history": history,
        }

    @staticmethod
    def _get_risk_color(risk_score: float) -> str:
        """Get color for risk visualization.

        Args:
            risk_score: Risk score (0-10)

        Returns:
            Color name (green/yellow/orange/red)
        """
        if risk_score < 2:
            return "green"
        elif risk_score < 5:
            return "yellow"
        elif risk_score < 7:
            return "orange"
        else:
            return "red"

    @staticmethod
    def _get_risk_level(risk_score: float) -> str:
        """Get risk level name.

        Args:
            risk_score: Risk score (0-10)

        Returns:
            Level name (low/medium/high/critical)
        """
        if risk_score < 3:
            return "low"
        elif risk_score < 5:
            return "medium"
        elif risk_score < 7:
            return "high"
        else:
            return "critical"
