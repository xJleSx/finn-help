"""Impact influence matrix and sector risk calculation.

Defines how different news types impact sectors with varying intensities.
Calculates daily sector risk scores based on accumulated news impacts.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Impact intensity matrix: news_type × sector → impact multiplier
IMPACT_MATRIX = {
    "sanctions": {
        "energy": 0.95,
        "metals": 0.90,
        "banking": 0.85,
        "tech": 0.50,
        "manufacturing": 0.70,
        "agriculture": 0.60,
        "retail": 0.30,
        "healthcare": 0.20,
        "transport": 0.40,
        "utilities": 0.60,
    },
    "conflict": {
        "energy": 0.80,
        "transport": 0.75,
        "tech": 0.50,
        "banking": 0.60,
        "defense": 0.95,
        "utilities": 0.40,
        "manufacturing": 0.50,
        "metals": 0.70,
        "agriculture": 0.50,
        "retail": 0.30,
    },
    "trade_war": {
        "tech": 0.90,
        "manufacturing": 0.85,
        "agriculture": 0.80,
        "retail": 0.70,
        "energy": 0.50,
        "metals": 0.75,
        "banking": 0.40,
        "transport": 0.50,
        "utilities": 0.30,
        "healthcare": 0.20,
    },
    "monetary_policy": {
        "banking": 0.90,
        "retail": 0.70,
        "tech": 0.80,
        "real_estate": 0.80,
        "manufacturing": 0.50,
        "energy": 0.40,
        "utilities": 0.50,
        "metals": 0.60,
        "agriculture": 0.30,
        "healthcare": 0.20,
    },
    "inflation": {
        "energy": 0.80,
        "metals": 0.75,
        "agriculture": 0.70,
        "manufacturing": 0.60,
        "transport": 0.70,
        "utilities": 0.65,
        "retail": 0.60,
        "banking": 0.50,
        "tech": 0.40,
        "healthcare": 0.40,
    },
    "geopolitical_risk": {
        "energy": 0.70,
        "banking": 0.50,
        "tech": 0.40,
        "manufacturing": 0.50,
        "metals": 0.60,
        "defense": 0.90,
        "transport": 0.50,
        "utilities": 0.40,
        "agriculture": 0.40,
        "retail": 0.30,
    },
}

# Impact decay function: how quickly news relevance decays
IMPACT_DECAY_PARAMS = {
    "half_life_days": 30,  # Impact halves after 30 days
    "min_impact": 0.05,  # Minimum impact threshold
}


class ImpactMatrix:
    """Manages impact calculations and sector risk aggregation."""

    def __init__(self):
        """Initialize impact matrix."""
        self.matrix = IMPACT_MATRIX
        self.decay_params = IMPACT_DECAY_PARAMS

    def get_impact(
        self, news_type: str, sector: str, base_impact_score: float
    ) -> float:
        """Calculate impact of news on a sector.

        Args:
            news_type: Type of news (sanctions, conflict, etc.)
            sector: Target sector
            base_impact_score: Base impact score (0-10)

        Returns:
            Calculated impact (0-10)
        """
        if news_type not in self.matrix:
            news_type = "geopolitical_risk"

        multiplier = self.matrix[news_type].get(sector, 0.3)  # Default low multiplier
        impact = base_impact_score * multiplier

        return min(10, max(0, impact))

    def calculate_decay(self, published_at: datetime, current_date: Optional[datetime] = None) -> float:
        """Calculate decay factor for aged news.

        Args:
            published_at: Article publication date
            current_date: Reference date (default: now)

        Returns:
            Decay factor (0-1, where 1 = no decay)
        """
        if current_date is None:
            current_date = datetime.now(timezone.utc)

        if not published_at:
            return 1.0

        days_old = (current_date - published_at).days
        if days_old < 0:
            return 1.0

        half_life = self.decay_params["half_life_days"]
        decay_factor = 0.5 ** (days_old / half_life)

        min_impact = self.decay_params["min_impact"]
        return max(min_impact, decay_factor)

    def calculate_sector_daily_risk(
        self, sector: str, news_articles: list[Any], current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Calculate daily risk score for a sector based on news.

        Args:
            sector: Sector name
            news_articles: List of relevant News ORM objects
            current_date: Reference date (default: now)

        Returns:
            Risk score dict with components
        """
        if current_date is None:
            current_date = datetime.now(timezone.utc)

        total_risk = 0.0
        news_count = 0
        top_risks = []

        for article in news_articles:
            if not article.is_relevant or not article.impact_score:
                continue

            # Get impact from news type (use subcategory if available)
            news_type = article.subcategory or "geopolitical_risk"
            impact = self.get_impact(news_type, sector, article.impact_score)

            # Apply decay
            decay = self.calculate_decay(article.published_at, current_date)
            adjusted_impact = impact * decay

            # Apply sentiment adjustment
            sentiment_multiplier = 1.0
            if article.sentiment == "positive":
                sentiment_multiplier = 0.7
            elif article.sentiment == "negative":
                sentiment_multiplier = 1.3

            final_impact = adjusted_impact * sentiment_multiplier

            total_risk += final_impact
            news_count += 1

            top_risks.append({
                "article_id": article.id,
                "title": article.title,
                "impact": final_impact,
                "published_at": article.published_at,
            })

        # Sort top risks
        top_risks.sort(key=lambda x: x["impact"], reverse=True)
        top_risks = top_risks[:5]  # Keep top 5

        # Average risk score
        avg_risk = total_risk / max(1, news_count) if news_count > 0 else 0

        return {
            "sector": sector,
            "date": current_date.date(),
            "total_risk": min(10, total_risk),
            "avg_risk": min(10, avg_risk),
            "article_count": news_count,
            "top_risks": top_risks,
        }

    def calculate_all_sectors_daily_risk(
        self, sectors: list[str], db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Calculate daily risk for all sectors.

        Args:
            sectors: List of sector names
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Dict with sector → risk score mappings
        """
        from src.db.models import News

        if current_date is None:
            current_date = datetime.now(timezone.utc)

        results = {}

        for sector in sectors:
            # Get relevant news for this sector (simplified - in production use news_sector_impacts)
            articles = db_session.query(News).filter(
                News.is_relevant,
                News.published_at >= current_date - timedelta(days=90),  # Last 90 days
            ).all()

            sector_risk = self.calculate_sector_daily_risk(sector, articles, current_date)
            results[sector] = sector_risk

        return results

    def calculate_trend(
        self, sector: str, db_session: Any, days: int = 30
    ) -> dict[str, Any]:
        """Calculate risk trend for a sector over time.

        Args:
            sector: Sector name
            db_session: Database session
            days: Number of days to analyze

        Returns:
            Trend data with risk progression
        """
        from src.db.models import News

        trend_data = []
        current_date = datetime.now(timezone.utc)

        for day_offset in range(days, -1, -1):
            date = current_date - timedelta(days=day_offset)

            articles = db_session.query(News).filter(
                News.is_relevant,
                News.published_at >= date - timedelta(days=1),
                News.published_at < date + timedelta(days=1),
            ).all()

            risk = self.calculate_sector_daily_risk(sector, articles, date)
            trend_data.append({
                "date": date.date(),
                "risk_score": risk["avg_risk"],
                "article_count": risk["article_count"],
            })

        # Calculate trend (simple linear regression)
        if len(trend_data) > 1:
            scores = [d["risk_score"] for d in trend_data]
            trend_direction = "up" if scores[-1] > scores[0] else "down"
            trend_magnitude = abs(scores[-1] - scores[0])
        else:
            trend_direction = "flat"
            trend_magnitude = 0.0

        return {
            "sector": sector,
            "period_days": days,
            "trend_direction": trend_direction,
            "trend_magnitude": min(10, trend_magnitude),
            "current_risk": trend_data[-1]["risk_score"] if trend_data else 0.0,
            "daily_data": trend_data,
        }

    def calculate_source_diversity_score(
        self, sector: str, db_session: Any, days: int = 30
    ) -> float:
        """Calculate source diversity score (higher = more reliable).

        Args:
            sector: Sector name
            db_session: Database session
            days: Time window

        Returns:
            Diversity score (0-1)
        """
        from src.db.models import News

        articles = db_session.query(News).filter(
            News.is_relevant,
            News.published_at >= datetime.now(timezone.utc) - timedelta(days=days),
        ).all()

        if not articles:
            return 0.0

        sources = set(a.source_name for a in articles if a.source_name)
        source_count = len(sources)

        # Diversity score increases with number of sources (max 10 sources = 1.0)
        diversity = min(1.0, source_count / 10.0)

        return diversity
