"""Sector Impact Engine - aggregates impacts and calculates sector risk.

Combines news impacts, commodity chains, and geopolitical factors to produce
comprehensive sector risk assessments.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

SECTOR_CORRELATION_MATRIX: dict[str, dict[str, float]] = {}


class EWMARiskCalculator:
    """Exponentially Weighted Moving Average risk calculator."""

    def __init__(self, alpha: float = 0.3, momentum_window: int = 7):
        self.alpha = alpha
        self.momentum_window = momentum_window

    def calculate(self, scores: list[float], weights: list[float] | None = None) -> float:
        if not scores:
            return 0.0
        if weights is not None and len(weights) == len(scores):
            return sum(s * w for s, w in zip(scores, weights)) / max(sum(weights), 1e-10)
        ewma = scores[0]
        for s in scores[1:]:
            ewma = self.alpha * s + (1 - self.alpha) * ewma
        return max(0, min(10, ewma))

    def momentum(self, scores: list[float]) -> float:
        if len(scores) < 2:
            return 0.0
        recent = scores[-min(self.momentum_window, len(scores)):]
        earlier = scores[:-len(recent)] or [0.0]
        avg_recent = sum(recent) / len(recent)
        avg_earlier = sum(earlier) / len(earlier)
        return avg_recent - avg_earlier

    def confidence(self, article_count: int) -> float:
        return min(1.0, article_count / 20.0)


class SectorCorrelationTracker:
    def __init__(self):
        self.matrix: dict[str, dict[str, float]] = {}

    def load_from_history(self, db: Any, days: int = 90) -> None:
        from src.db.models import SectorRiskHistory

        history = db.query(SectorRiskHistory).filter(
            SectorRiskHistory.date >= datetime.now(timezone.utc).date() - timedelta(days=days),
        ).order_by(SectorRiskHistory.date).all()

        by_sector: dict[str, list[float]] = {}
        for h in history:
            by_sector.setdefault(h.sector, []).append(h.risk_score)

        sectors = list(by_sector.keys())
        for s1 in sectors:
            self.matrix.setdefault(s1, {})
            for s2 in sectors:
                if s1 == s2:
                    self.matrix[s1][s2] = 1.0
                    continue
                v1, v2 = by_sector[s1], by_sector[s2]
                n = min(len(v1), len(v2))
                if n < 5:
                    self.matrix[s1][s2] = 0.0
                    continue
                m1, m2 = sum(v1[:n]) / n, sum(v2[:n]) / n
                d1 = sum((x - m1) ** 2 for x in v1[:n])
                d2 = sum((x - m2) ** 2 for x in v2[:n])
                if d1 == 0 or d2 == 0:
                    self.matrix[s1][s2] = 0.0
                    continue
                cov = sum((v1[i] - m1) * (v2[i] - m2) for i in range(n))
                self.matrix[s1][s2] = max(-1.0, min(1.0, cov / ((d1 * d2) ** 0.5)))

    def get_contagion_risk(self, sector: str, threshold: float = 0.5) -> list[tuple[str, float]]:
        if sector not in self.matrix:
            return []
        result = []
        for other, corr in self.matrix[sector].items():
            if other != sector and abs(corr) >= threshold:
                result.append((other, corr))
        return sorted(result, key=lambda x: -abs(x[1]))

    def update_from_daily(self, sector: str, risk_score: float) -> None:
        pass  # Called after each daily calc; history query handles updates


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
        if current_date is None:
            current_date = datetime.now(timezone.utc)

        from src.db.models import NewsSectorImpact

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
                "ewma_score": 0.0,
                "momentum": 0.0,
                "confidence": 0.0,
                "contagion_sectors": [],
            }

        ewma_calc = EWMARiskCalculator()

        components: dict[str, dict[str, float]] = {}
        all_scores: list[float] = []
        sentiment_sum = 0.0
        sentiment_count = 0

        for impact in impacts:
            impact_type = impact.impact_type
            if impact_type not in components:
                components[impact_type] = {"count": 0, "total": 0.0, "avg": 0.0}
            components[impact_type]["count"] += 1
            components[impact_type]["total"] += impact.impact_score
            all_scores.append(impact.impact_score)

            if hasattr(impact, "intensity") and impact.intensity:
                sentiment_sum += impact.intensity
                sentiment_count += 1

        for impact_type in components:
            components[impact_type]["avg"] = (
                components[impact_type]["total"] / max(components[impact_type]["count"], 1)
            )

        risk_score = ewma_calc.calculate(all_scores)
        momentum = ewma_calc.momentum(all_scores)
        confidence = ewma_calc.confidence(len(impacts))

        # Sentiment multiplier
        sentiment_mult = 1.0
        if sentiment_count > 0:
            avg_sent = sentiment_sum / sentiment_count
            sentiment_mult = 1.0 + (avg_sent - 1.0) * 0.3

        risk_score = max(0, min(10, risk_score * sentiment_mult))

        # Contagion
        tracker = getattr(self, "_correlation_tracker", None)
        contagion = []
        if tracker is not None:
            contagion = tracker.get_contagion_risk(sector)

        return {
            "sector": sector,
            "date": current_date.date(),
            "risk_score": round(risk_score, 2),
            "components": components,
            "article_count": len(impacts),
            "total_impact": round(sum(all_scores), 2),
            "ewma_score": round(risk_score, 2),
            "momentum": round(momentum, 2),
            "confidence": round(confidence, 2),
            "sentiment_multiplier": round(sentiment_mult, 2),
            "contagion_sectors": contagion,
        }

    def calculate_all_sectors_daily_risk(
        self, sectors: list[str], db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        results = {}

        tracker = SectorCorrelationTracker()
        self._correlation_tracker = tracker
        tracker.load_from_history(db_session)

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
            SectorRiskHistory.date >= datetime.now(timezone.utc).date() - timedelta(days=days),
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

        today = datetime.now(timezone.utc).date()
        high_risk = db_session.query(SectorRiskHistory).filter(
            SectorRiskHistory.date == today,
            SectorRiskHistory.risk_score >= threshold,
        ).all()

        return list(set(h.sector for h in high_risk))

    def get_daily_risk_v2(
        self, sector: str, db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        result = self.calculate_daily_sector_risk(sector, db_session, current_date)

        if self._correlation_tracker is None:
            self._correlation_tracker = SectorCorrelationTracker()
            self._correlation_tracker.load_from_history(db_session)

        result["contagion_sectors"] = self._correlation_tracker.get_contagion_risk(sector)

        trend = self.get_sector_trend(sector, db_session)
        result["trend"] = trend["trend"]

        regime = "high" if result["risk_score"] > 7 else "medium" if result["risk_score"] > 4 else "low"
        result["regime"] = regime

        return result

    def get_risk_heatmap(
        self, db_session: Any, sectors: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
        from src.db.models import Instrument

        if sectors is None:
            sectors = [
                r[0] for r in db_session.query(Instrument.sector).distinct().all() if r[0]
            ]

        tracker = SectorCorrelationTracker()
        tracker.load_from_history(db_session)

        results = []
        for sector in sectors:
            risk = self.calculate_daily_sector_risk(sector, db_session)
            contagion = tracker.get_contagion_risk(sector)
            results.append({
                "sector": sector,
                "risk_score": risk["risk_score"],
                "momentum": risk["momentum"],
                "confidence": risk["confidence"],
                "article_count": risk["article_count"],
                "contagion": [s for s, _ in contagion[:3]],
                "regime": "high" if risk["risk_score"] > 7 else "medium" if risk["risk_score"] > 4 else "low",
            })

        return sorted(results, key=lambda x: -x["risk_score"])

    def cascade_sector_impacts(
        self, primary_sector: str, db_session: Any
    ) -> dict[str, Any]:
        cascades = self.sector_mapper.get_cascading_effects([primary_sector])
        return cascades
