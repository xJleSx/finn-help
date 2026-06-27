"""Company Risk Aggregator - combines sector, geopolitical, macro, and company-specific risks.

Calculates comprehensive risk score for each instrument based on multiple factors.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Risk component weights
RISK_WEIGHTS = {
    "sector_risk": 0.30,
    "geopolitical_risk": 0.30,
    "macro_risk": 0.20,
    "company_specific_risk": 0.20,
}


class CompanyRiskAggregator:
    """Aggregates multiple risk sources into comprehensive company risk scores."""

    def __init__(self):
        """Initialize aggregator."""
        self.weights = RISK_WEIGHTS

    def calculate_sector_risk_component(
        self, instrument: Any, db_session: Any, current_date: Optional[datetime] = None
    ) -> float:
        """Calculate sector-specific risk component for an instrument.

        Args:
            instrument: Instrument ORM object
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Risk score (0-10)
        """
        from src.db.models import SectorRiskHistory

        if current_date is None:
            current_date = datetime.utcnow()

        if not instrument.sector:
            return 0.0

        # Get today's sector risk
        sector_risk = db_session.query(SectorRiskHistory).filter(
            SectorRiskHistory.sector == instrument.sector,
            SectorRiskHistory.date == current_date.date(),
        ).first()

        return sector_risk.risk_score if sector_risk else 0.0

    def calculate_geopolitical_risk_component(
        self, db_session: Any, current_date: Optional[datetime] = None
    ) -> float:
        """Calculate geopolitical risk component (affects all instruments).

        Args:
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Risk score (0-10)
        """
        from src.db.models import GeopoliticalRiskHistory

        if current_date is None:
            current_date = datetime.utcnow()

        geo_risk = db_session.query(GeopoliticalRiskHistory).filter(
            GeopoliticalRiskHistory.date == current_date.date()
        ).first()

        return geo_risk.risk_score if geo_risk else 0.0

    def calculate_macro_risk_component(
        self, db_session: Any, current_date: Optional[datetime] = None
    ) -> float:
        """Calculate macro risk component (interest rates, inflation, etc).

        Args:
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Risk score (0-10)
        """
        from src.db.models import NewsCompanyImpact

        if current_date is None:
            current_date = datetime.utcnow()

        # Get macro-related impacts from news
        macro_impacts = db_session.query(NewsCompanyImpact).filter(
            NewsCompanyImpact.impact_type == "monetary",
            NewsCompanyImpact.created_at >= current_date - timedelta(days=30),
        ).all()

        if not macro_impacts:
            return 0.0

        avg_impact = sum(m.impact_score for m in macro_impacts) / len(macro_impacts)
        return min(10, avg_impact)

    def calculate_company_specific_risk_component(
        self, instrument: Any, db_session: Any, current_date: Optional[datetime] = None
    ) -> float:
        """Calculate company-specific risk (earnings, management, etc).

        Args:
            instrument: Instrument ORM object
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Risk score (0-10)
        """
        from src.db.models import NewsCompanyImpact

        if current_date is None:
            current_date = datetime.utcnow()

        # Get company-specific impacts
        company_impacts = db_session.query(NewsCompanyImpact).filter(
            NewsCompanyImpact.instrument_id == instrument.id,
            NewsCompanyImpact.impact_type == "company_specific",
            NewsCompanyImpact.created_at >= current_date - timedelta(days=30),
        ).all()

        if not company_impacts:
            return 0.0

        avg_impact = sum(m.impact_score for m in company_impacts) / len(company_impacts)
        return min(10, avg_impact)

    def calculate_company_risk(
        self, instrument: Any, db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Calculate comprehensive risk score for a company.

        Args:
            instrument: Instrument ORM object
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Risk assessment dict
        """
        if current_date is None:
            current_date = datetime.utcnow()

        # Calculate components
        sector_risk = self.calculate_sector_risk_component(instrument, db_session, current_date)
        geo_risk = self.calculate_geopolitical_risk_component(db_session, current_date)
        macro_risk = self.calculate_macro_risk_component(db_session, current_date)
        company_risk = self.calculate_company_specific_risk_component(
            instrument, db_session, current_date
        )

        # Weighted combination
        total_risk = (
            sector_risk * self.weights["sector_risk"]
            + geo_risk * self.weights["geopolitical_risk"]
            + macro_risk * self.weights["macro_risk"]
            + company_risk * self.weights["company_specific_risk"]
        )

        # Account for recency: recent news has higher impact
        from src.db.models import NewsCompanyImpact

        recent_impacts = db_session.query(NewsCompanyImpact).filter(
            NewsCompanyImpact.instrument_id == instrument.id,
            NewsCompanyImpact.created_at >= current_date - timedelta(days=7),
        ).all()

        recency_multiplier = 1.0
        if recent_impacts:
            recency_multiplier = 1.2  # 20% boost for recent risk

        # Account for sentiment
        from src.db.models import News, NewsInstrument

        recent_news = db_session.query(News).join(
            NewsInstrument, NewsInstrument.news_id == News.id
        ).filter(
            NewsInstrument.instrument_id == instrument.id,
            News.published_at >= current_date - timedelta(days=30),
        ).all()

        negative_count = sum(1 for n in recent_news if n.sentiment == "negative")

        if recent_news:
            sentiment_ratio = negative_count / len(recent_news)
            sentiment_multiplier = 0.8 + sentiment_ratio * 0.4  # 0.8-1.2 range
        else:
            sentiment_multiplier = 1.0

        final_risk = total_risk * recency_multiplier * sentiment_multiplier

        return {
            "instrument_id": instrument.id,
            "ticker": instrument.ticker,
            "date": current_date.date(),
            "risk_score": min(10, max(0, final_risk)),
            "components": {
                "sector_risk": sector_risk,
                "geopolitical_risk": geo_risk,
                "macro_risk": macro_risk,
                "company_specific_risk": company_risk,
            },
            "multipliers": {
                "recency_multiplier": recency_multiplier,
                "sentiment_multiplier": sentiment_multiplier,
            },
            "recent_news_count": len(recent_news),
        }

    def batch_calculate_company_risks(
        self, instruments: list[Any], db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[int, dict[str, Any]]:
        """Calculate risk for multiple instruments.

        Args:
            instruments: List of Instrument ORM objects
            db_session: Database session
            current_date: Reference date (default: now)

        Returns:
            Dict mapping instrument_id → risk_assessment
        """
        results = {}

        for instrument in instruments:
            risk = self.calculate_company_risk(instrument, db_session, current_date)
            results[instrument.id] = risk

        return results

    def store_company_risk(
        self, company_risk: dict[str, Any], db_session: Any
    ) -> bool:
        """Store company risk to history table.

        Args:
            company_risk: Risk assessment from calculate_company_risk
            db_session: Database session

        Returns:
            True if stored successfully
        """
        from src.db.models import CompanyRiskHistory

        try:
            history_record = CompanyRiskHistory(
                instrument_id=company_risk["instrument_id"],
                date=company_risk["date"],
                risk_score=company_risk["risk_score"],
                sector_risk=company_risk["components"]["sector_risk"],
                geopolitical_risk=company_risk["components"]["geopolitical_risk"],
                macro_risk=company_risk["components"]["macro_risk"],
                company_specific_risk=company_risk["components"]["company_specific_risk"],
                components_json=company_risk["components"],
                article_count=company_risk.get("recent_news_count", 0),
            )
            db_session.add(history_record)
            db_session.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to store company risk for {company_risk.get('ticker')}: {e}")
            return False

    def get_high_risk_companies(
        self, db_session: Any, threshold: float = 6.5, count: int = 20
    ) -> list[dict[str, Any]]:
        """Get companies with highest risk scores.

        Args:
            db_session: Database session
            threshold: Minimum risk score
            count: Max number of results

        Returns:
            List of high-risk company dicts
        """
        from src.db.models import CompanyRiskHistory, Instrument

        today = datetime.utcnow().date()

        high_risk = db_session.query(CompanyRiskHistory).filter(
            CompanyRiskHistory.date == today,
            CompanyRiskHistory.risk_score >= threshold,
        ).order_by(CompanyRiskHistory.risk_score.desc()).limit(count).all()

        results = []
        for risk in high_risk:
            instrument = db_session.query(Instrument).get(risk.instrument_id)
            results.append({
                "ticker": instrument.ticker if instrument else "UNKNOWN",
                "risk_score": risk.risk_score,
                "sector_risk": risk.sector_risk,
                "geopolitical_risk": risk.geopolitical_risk,
                "macro_risk": risk.macro_risk,
                "company_specific_risk": risk.company_specific_risk,
            })

        return results

    def get_company_risk_trend(
        self, instrument: Any, db_session: Any, days: int = 30
    ) -> dict[str, Any]:
        """Get risk trend for a company.

        Args:
            instrument: Instrument ORM object
            db_session: Database session
            days: Number of days to analyze

        Returns:
            Trend data
        """
        from src.db.models import CompanyRiskHistory

        history = db_session.query(CompanyRiskHistory).filter(
            CompanyRiskHistory.instrument_id == instrument.id,
            CompanyRiskHistory.date >= datetime.utcnow().date() - timedelta(days=days),
        ).order_by(CompanyRiskHistory.date).all()

        if not history:
            return {
                "ticker": instrument.ticker,
                "trend": "no_data",
                "current_risk": 0.0,
                "average_risk": 0.0,
            }

        scores = [h.risk_score for h in history]
        current = scores[-1] if scores else 0.0
        average = sum(scores) / len(scores) if scores else 0.0

        # Trend direction
        if len(scores) > 1:
            trend = "up" if scores[-1] > scores[0] else "down"
        else:
            trend = "flat"

        return {
            "ticker": instrument.ticker,
            "trend": trend,
            "current_risk": current,
            "average_risk": average,
            "history": [{"date": h.date, "risk": h.risk_score} for h in history],
        }
