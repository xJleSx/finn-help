"""Geopolitical Risk Engine v2 - calculates geopolitical risk with subcategories.

Includes:
- Sanctions (35% weight)
- Conflict (30% weight)
- Trade war (20% weight)
- Diplomacy (15% weight)

Features recency weighting and source diversity scoring.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Subcategory weights for geopolitical risk
GEO_RISK_WEIGHTS = {
    "sanctions": 0.35,
    "conflict": 0.30,
    "trade_war": 0.20,
    "diplomacy": 0.15,
}

# Impact multipliers by region
REGIONAL_MULTIPLIERS = {
    "russia": 1.2,  # Increase local impacts
    "china": 1.1,
    "europe": 0.9,
    "usa": 0.8,
    "middle_east": 1.0,
}


class GeopoliticalRiskEngine:
    """Calculates comprehensive geopolitical risk scores."""

    def __init__(self):
        """Initialize engine."""
        self.weights = GEO_RISK_WEIGHTS
        self.regional_multipliers = REGIONAL_MULTIPLIERS

    def extract_region_from_news(self, title: str, summary: str) -> Optional[str]:
        """Extract mentioned region/country from news text.

        Args:
            title: Article title
            summary: Article summary

        Returns:
            Region name or None
        """
        text = f"{title} {summary}".lower()

        region_keywords = {
            "russia": ["россия", "russian", "рф", "кремль", "москва"],
            "china": ["china", "chinese", "пекин", "peking"],
            "europe": ["европа", "european", "евросоюз", "eu"],
            "usa": ["usa", "american", "washington", "сша"],
            "middle_east": ["middle east", "иран", "саудовская аравия", "израиль"],
        }

        for region, keywords in region_keywords.items():
            if any(kw in text for kw in keywords):
                return region

        return None

    def calculate_subcategory_score(
        self, subcategory: str, articles: list[Any], current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Calculate risk score for a geopolitical subcategory.

        Args:
            subcategory: Subcategory name (sanctions, conflict, etc)
            articles: List of relevant News ORM objects
            current_date: Reference date (default: now)

        Returns:
            Risk assessment for subcategory
        """
        if current_date is None:
            current_date = datetime.utcnow()

        relevant_articles = [
            a for a in articles
            if a.is_relevant and a.subcategory == subcategory
        ]

        if not relevant_articles:
            return {
                "subcategory": subcategory,
                "risk_score": 0.0,
                "article_count": 0,
                "sources": set(),
            }

        total_risk = 0.0
        sources = set()

        for article in relevant_articles:
            # Apply decay
            days_old = (current_date - (article.published_at or current_date)).days
            decay = 0.5 ** (days_old / 30)  # Half-life of 30 days

            # Apply sentiment multiplier
            sentiment_mult = 1.0
            if article.sentiment == "positive":
                sentiment_mult = 0.7
            elif article.sentiment == "negative":
                sentiment_mult = 1.3

            # Calculate adjusted impact
            impact = (article.impact_score or 5) * decay * sentiment_mult
            total_risk += impact

            if article.source_name:
                sources.add(article.source_name)

        # Average risk (cap at 10)
        avg_risk = min(10, total_risk / len(relevant_articles))

        return {
            "subcategory": subcategory,
            "risk_score": avg_risk,
            "article_count": len(relevant_articles),
            "sources": sources,
            "source_count": len(sources),
        }

    def calculate_daily_geopolitical_risk(
        self, db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Calculate daily geopolitical risk with all subcategories.

        Args:
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Comprehensive geopolitical risk assessment
        """
        from src.db.models import News

        if current_date is None:
            current_date = datetime.utcnow()

        # Get geopolitical news from last 90 days
        geo_articles = db_session.query(News).filter(
            News.category == "GEOPOLITICAL",
            News.is_relevant,
            News.published_at >= current_date - timedelta(days=90),
        ).all()

        if not geo_articles:
            return {
                "date": current_date.date(),
                "risk_score": 0.0,
                "subcategories": {},
                "article_count": 0,
                "sources": [],
            }

        # Calculate scores by subcategory
        subcategories = {}
        all_sources = set()
        total_weighted_risk = 0.0

        for subcat, weight in self.weights.items():
            subcat_result = self.calculate_subcategory_score(subcat, geo_articles, current_date)
            subcategories[subcat] = {
                "risk_score": subcat_result["risk_score"],
                "article_count": subcat_result["article_count"],
            }

            all_sources.update(subcat_result["sources"])
            total_weighted_risk += subcat_result["risk_score"] * weight

        # Calculate overall risk (weighted sum)
        overall_risk = min(10, total_weighted_risk)

        # Apply source diversity multiplier (more sources = more reliable)
        source_diversity = min(1.0, len(all_sources) / 10.0)
        diversity_multiplier = 0.8 + source_diversity * 0.4  # 0.8-1.2 range

        final_risk = overall_risk * diversity_multiplier

        return {
            "date": current_date.date(),
            "risk_score": min(10, final_risk),
            "subcategories": {
                "sanctions": subcategories.get("sanctions", {"risk_score": 0.0}),
                "conflict": subcategories.get("conflict", {"risk_score": 0.0}),
                "trade_war": subcategories.get("trade_war", {"risk_score": 0.0}),
                "diplomacy": subcategories.get("diplomacy", {"risk_score": 0.0}),
            },
            "total_article_count": len(geo_articles),
            "unique_sources": len(all_sources),
            "source_diversity_score": source_diversity,
        }

    def calculate_geopolitical_trend(
        self, db_session: Any, days: int = 30
    ) -> dict[str, Any]:
        """Calculate geopolitical risk trend.

        Args:
            db_session: Database session
            days: Number of days to analyze

        Returns:
            Trend data with direction and magnitude
        """
        from src.db.models import GeopoliticalRiskHistory

        history = db_session.query(GeopoliticalRiskHistory).filter(
            GeopoliticalRiskHistory.date >= datetime.utcnow().date() - timedelta(days=days)
        ).order_by(GeopoliticalRiskHistory.date).all()

        if not history:
            return {
                "trend": "no_data",
                "current_risk": 0.0,
                "average_risk": 0.0,
                "max_risk": 0.0,
            }

        scores = [h.risk_score for h in history]
        current = scores[-1] if scores else 0.0
        average = sum(scores) / len(scores) if scores else 0.0
        max_risk = max(scores) if scores else 0.0

        # Determine trend
        if len(scores) > 1:
            trend_direction = "up" if scores[-1] > scores[0] else "down"
            trend_magnitude = abs(scores[-1] - scores[0])
        else:
            trend_direction = "flat"
            trend_magnitude = 0.0

        # Calculate trend line (simple linear)
        if len(scores) > 1:
            x = list(range(len(scores)))
            y = scores
            n = len(x)
            slope = (n * sum(a * b for a, b in zip(x, y)) - sum(x) * sum(y)) / (
                n * sum(a ** 2 for a in x) - sum(x) ** 2
            )
            trend_velocity = slope
        else:
            trend_velocity = 0.0

        return {
            "period_days": days,
            "trend": trend_direction,
            "trend_magnitude": min(10, trend_magnitude),
            "trend_velocity": trend_velocity,
            "current_risk": current,
            "average_risk": average,
            "max_risk": max_risk,
            "history": [{"date": h.date, "risk": h.risk_score} for h in history],
        }

    def store_geopolitical_risk(
        self, geo_risk: dict[str, Any], db_session: Any
    ) -> bool:
        """Store geopolitical risk to history table.

        Args:
            geo_risk: Risk assessment from calculate_daily_geopolitical_risk
            db_session: Database session

        Returns:
            True if stored successfully
        """
        from src.db.models import GeopoliticalRiskHistory

        try:
            history_record = GeopoliticalRiskHistory(
                date=geo_risk["date"],
                risk_score=geo_risk["risk_score"],
                sanctions_score=geo_risk["subcategories"]["sanctions"]["risk_score"],
                conflict_score=geo_risk["subcategories"]["conflict"]["risk_score"],
                trade_war_score=geo_risk["subcategories"]["trade_war"]["risk_score"],
                diplomacy_score=geo_risk["subcategories"]["diplomacy"]["risk_score"],
                components_json=geo_risk["subcategories"],
                sources_json={"unique_sources": geo_risk["unique_sources"]},
                article_count=geo_risk["total_article_count"],
            )
            db_session.add(history_record)
            db_session.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to store geopolitical risk: {e}")
            return False

    def get_risk_alert_level(self, risk_score: float) -> str:
        """Determine alert level based on risk score.

        Args:
            risk_score: Geopolitical risk score (0-10)

        Returns:
            Alert level (low/medium/high/critical)
        """
        if risk_score < 3:
            return "low"
        elif risk_score < 5:
            return "medium"
        elif risk_score < 7:
            return "high"
        else:
            return "critical"

    def identify_emerging_threats(
        self, db_session: Any, sensitivity: float = 0.2
    ) -> list[dict[str, Any]]:
        """Identify emerging geopolitical threats (rapid increases in risk).

        Args:
            db_session: Database session
            sensitivity: Change threshold for detection (0-1)

        Returns:
            List of emerging threats
        """
        from src.db.models import GeopoliticalRiskHistory

        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)

        today_risk = db_session.query(GeopoliticalRiskHistory).filter(
            GeopoliticalRiskHistory.date == today
        ).first()
        yesterday_risk = db_session.query(GeopoliticalRiskHistory).filter(
            GeopoliticalRiskHistory.date == yesterday
        ).first()
        week_risk = db_session.query(GeopoliticalRiskHistory).filter(
            GeopoliticalRiskHistory.date == week_ago
        ).first()

        threats = []

        if today_risk and yesterday_risk:
            day_change = today_risk.risk_score - yesterday_risk.risk_score
            if day_change > sensitivity * 10:  # Significant day-over-day increase
                threats.append({
                    "type": "spike",
                    "magnitude": day_change,
                    "period": "1_day",
                    "current_level": today_risk.risk_score,
                })

        if today_risk and week_risk:
            week_change = today_risk.risk_score - week_risk.risk_score
            if week_change > sensitivity * 10:
                threats.append({
                    "type": "trend",
                    "magnitude": week_change,
                    "period": "7_days",
                    "current_level": today_risk.risk_score,
                })

        return threats
