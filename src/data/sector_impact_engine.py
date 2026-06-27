"""Sector Impact Engine - aggregates impacts and calculates sector risk.

Combines news impacts, commodity chains, and geopolitical factors to produce
comprehensive sector risk assessments.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SectorImpactEngine:
    """Main engine for calculating sector-level impacts and risks."""

    def __init__(self, impact_matrix: Any, sector_mapper: Any):
        """Initialize engine.

        Args:
            impact_matrix: ImpactMatrix instance
            sector_mapper: SectorMapper instance
        """
        self.impact_matrix = impact_matrix
        self.sector_mapper = sector_mapper

    def calculate_sector_impact_from_news(
        self, news_article: Any, db_session: Any
    ) -> dict[str, Any]:
        """Calculate sector impacts from a single news article.

        Args:
            news_article: News ORM object
            db_session: Database session

        Returns:
            Dict mapping sector_name → impact_details
        """
        if not news_article.is_relevant:
            return {}

        # Analyze sector exposure
        text = f"{news_article.title or ''} {news_article.summary or ''}"
        sector_exposure = self.sector_mapper.analyze_sector_exposure(
            news_article.category or "MACRO",
            news_article.subcategory or "",
            text,
            db_session,
        )

        impacts = {}

        # Primary sector impacts
        for sector, details in sector_exposure["primary_sectors"].items():
            base_impact = self.impact_matrix.get_impact(
                news_article.subcategory or "geopolitical_risk",
                sector,
                news_article.impact_score or 5,
            )

            decay = self.impact_matrix.calculate_decay(news_article.published_at)
            final_impact = base_impact * decay

            impacts[sector] = {
                "impact_type": details["impact_type"],
                "intensity": details["intensity"],
                "calculated_impact": final_impact,
                "decay_factor": decay,
                "sentiment_multiplier": self._get_sentiment_multiplier(
                    news_article.sentiment
                ),
            }

        # Cascade sector impacts (reduced intensity)
        for sector, details in sector_exposure["cascade_sectors"].items():
            base_impact = self.impact_matrix.get_impact(
                details["impact_type"],
                sector,
                news_article.impact_score or 5,
            )

            decay = self.impact_matrix.calculate_decay(news_article.published_at)
            cascade_reduction = 0.6  # Cascades are 60% as strong
            final_impact = base_impact * decay * cascade_reduction

            impacts[sector] = {
                "impact_type": "cascade",
                "intensity": details["intensity"] * cascade_reduction,
                "calculated_impact": final_impact,
                "decay_factor": decay,
                "via_sector": details["via_sector"],
            }

        return impacts

    def store_news_sector_impacts(
        self, news_article: Any, sector_impacts: dict[str, Any], db_session: Any
    ) -> int:
        """Store news-sector impact relationships in database.

        Args:
            news_article: News ORM object
            sector_impacts: Dict of sector impacts from calculate_sector_impact_from_news
            db_session: Database session

        Returns:
            Number of impacts stored
        """
        from src.db.models import NewsSectorImpact

        count = 0
        for sector, impact_details in sector_impacts.items():
            impact_record = NewsSectorImpact(
                news_id=news_article.id,
                sector=sector,
                impact_type=impact_details["impact_type"],
                impact_score=impact_details["calculated_impact"],
                intensity=impact_details["intensity"],
            )
            db_session.add(impact_record)
            count += 1

        db_session.flush()
        return count

    def _get_sentiment_multiplier(self, sentiment: Optional[str]) -> float:
        """Get sentiment impact multiplier.

        Args:
            sentiment: Article sentiment (positive/negative/neutral)

        Returns:
            Multiplier (0.7-1.3)
        """
        if sentiment == "positive":
            return 0.7
        elif sentiment == "negative":
            return 1.3
        return 1.0

    def calculate_daily_sector_risk(
        self, sector: str, db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Calculate comprehensive daily risk for a sector.

        Args:
            sector: Sector name
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Risk assessment dict
        """
        if current_date is None:
            current_date = datetime.utcnow()

        from src.db.models import NewsSectorImpact

        # Get all impacts on sector from last 90 days
        impacts = db_session.query(NewsSectorImpact).filter(
            NewsSectorImpact.sector == sector,
            NewsSectorImpact.created_at >= current_date - timedelta(days=90),
        ).all()

        if not impacts:
            return {
                "sector": sector,
                "date": current_date.date(),
                "risk_score": 0.0,
                "components": {},
                "article_count": 0,
            }

        # Aggregate by impact type
        components = {}
        total_risk = 0.0

        for impact in impacts:
            impact_type = impact.impact_type
            if impact_type not in components:
                components[impact_type] = {
                    "count": 0,
                    "total": 0.0,
                    "avg": 0.0,
                }

            components[impact_type]["count"] += 1
            components[impact_type]["total"] += impact.impact_score
            total_risk += impact.impact_score

        # Calculate averages
        for impact_type in components:
            components[impact_type]["avg"] = (
                components[impact_type]["total"] / components[impact_type]["count"]
            )

        # Calculate overall sector risk (0-10 scale, then normalize)
        risk_score = min(10, total_risk / max(1, len(impacts)))

        return {
            "sector": sector,
            "date": current_date.date(),
            "risk_score": risk_score,
            "components": components,
            "article_count": len(impacts),
            "total_impact": total_risk,
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
            Dict mapping sector_name → risk_assessment
        """
        results = {}

        for sector in sectors:
            risk = self.calculate_daily_sector_risk(sector, db_session, current_date)
            results[sector] = risk

        return results

    def store_daily_sector_risk(
        self, sector: str, risk_assessment: dict[str, Any], db_session: Any
    ) -> bool:
        """Store daily sector risk to history table.

        Args:
            sector: Sector name
            risk_assessment: Risk assessment from calculate_daily_sector_risk
            db_session: Database session

        Returns:
            True if stored successfully
        """
        from src.db.models import SectorRiskHistory

        try:
            history_record = SectorRiskHistory(
                sector=sector,
                date=risk_assessment["date"],
                risk_score=risk_assessment["risk_score"],
                components_json=risk_assessment["components"],
                article_count=risk_assessment["article_count"],
            )
            db_session.add(history_record)
            db_session.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to store sector risk for {sector}: {e}")
            return False

    def get_sector_trend(
        self, sector: str, db_session: Any, days: int = 30
    ) -> dict[str, Any]:
        """Get risk trend for a sector.

        Args:
            sector: Sector name
            db_session: Database session
            days: Number of days to analyze

        Returns:
            Trend data
        """
        from src.db.models import SectorRiskHistory

        history = db_session.query(SectorRiskHistory).filter(
            SectorRiskHistory.sector == sector,
            SectorRiskHistory.date >= datetime.utcnow().date() - timedelta(days=days),
        ).order_by(SectorRiskHistory.date).all()

        if not history:
            return {
                "sector": sector,
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
            trend = "up" if scores[-1] > scores[0] else "down"
        else:
            trend = "flat"

        return {
            "sector": sector,
            "trend": trend,
            "current_risk": current,
            "average_risk": average,
            "max_risk": max_risk,
            "days": len(history),
            "history": [
                {"date": h.date, "risk": h.risk_score}
                for h in history
            ],
        }

    def identify_high_risk_sectors(
        self, db_session: Any, threshold: float = 6.0
    ) -> list[str]:
        """Identify sectors with risk above threshold.

        Args:
            db_session: Database session
            threshold: Risk score threshold (0-10)

        Returns:
            List of high-risk sector names
        """
        from src.db.models import SectorRiskHistory

        today = datetime.utcnow().date()
        high_risk = db_session.query(SectorRiskHistory).filter(
            SectorRiskHistory.date == today,
            SectorRiskHistory.risk_score >= threshold,
        ).all()

        return list(set(h.sector for h in high_risk))

    def cascade_sector_impacts(
        self, primary_sector: str, db_session: Any
    ) -> dict[str, Any]:
        """Analyze cascading effects from one sector to others.

        Args:
            primary_sector: Source sector
            db_session: Database session

        Returns:
            Dict of cascading impacts
        """
        cascades = self.sector_mapper.get_cascading_effects([primary_sector])
        return cascades
