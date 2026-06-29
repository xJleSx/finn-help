"""Company Risk Aggregator v2 - combines sector, geopolitical, macro, and company-specific risks.

Calculates comprehensive risk score for each instrument based on multiple factors.
Features:
  - Dynamic weights (regime-aware)
  - Volatility adjustment from price history
  - Correlation-based intra-sector contagion
  - Cap-class scaling
  - Confidence interval based on data availability
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

BASE_WEIGHTS: dict[str, float] = {
    "sector_risk": 0.30,
    "geopolitical_risk": 0.25,
    "macro_risk": 0.20,
    "company_specific_risk": 0.25,
}

SECTOR_BASELINE_RISK: dict[str, float] = {
    "Финансы": 5.5,
    "Нефть": 6.0,
    "IT": 4.0,
    "Металлы": 5.5,
    "Телеком": 4.5,
    "Энергетика": 5.0,
    "Транспорт": 5.0,
    "Потребтовары": 4.0,
    "Строительство": 5.5,
    "Химия": 4.5,
    "Машиностроение": 5.0,
    "Медицина": 3.5,
}

CONTAGION_COEFFICIENT = 0.15  # spillover from peer risk


class CompanyRiskAggregator:
    """Aggregates multiple risk sources into comprehensive company risk scores."""

    def __init__(self, weights: Optional[dict[str, float]] = None):
        self.weights = weights or dict(BASE_WEIGHTS)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _get_sector_baseline(sector: Optional[str]) -> float:
        return SECTOR_BASELINE_RISK.get(sector, 5.0)

    @staticmethod
    def _compute_volatility(
        db_session: Any, instrument_id: int, days: int = 60
    ) -> float:
        """Annualised volatility from daily log-returns (0-10 scale)."""
        from src.db.models import Price
        prices = (
            db_session.query(Price)
            .filter(
                Price.instrument_id == instrument_id,
                Price.close.isnot(None),
            )
            .order_by(Price.date.desc())
            .limit(days + 1)
            .all()
        )
        if len(prices) < 10:
            return 5.0  # neutral default
        closes = [p.close for p in reversed(prices)]
        returns = np.diff(np.log(closes))
        if len(returns) < 2:
            return 5.0
        vol = float(np.std(returns) * np.sqrt(252) * 100)  # annualised %
        return min(10.0, vol / 4.0)  # scale: 40% vol → 10

    @staticmethod
    def _get_market_regime(db_session: Any) -> str:
        """Determine broad market regime (normal / stress)."""
        from src.db.models import GeopoliticalRiskHistory, SectorRiskHistory
        today = datetime.utcnow().date()
        geo = (
            db_session.query(GeopoliticalRiskHistory)
            .filter(GeopoliticalRiskHistory.date == today)
            .first()
        )
        # average sector risk across all sectors today
        sectors = (
            db_session.query(SectorRiskHistory)
            .filter(SectorRiskHistory.date == today)
            .all()
        )
        avg_sector = (
            sum(s.risk_score for s in sectors) / len(sectors) if sectors else 5.0
        )
        geo_score = geo.risk_score if geo else 5.0
        combined = avg_sector * 0.5 + geo_score * 0.5
        if combined >= 7.0:
            return "stress"
        if combined >= 5.0:
            return "elevated"
        return "normal"

    def _adjust_weights(self, regime: str) -> dict[str, float]:
        if regime == "stress":
            return {
                "sector_risk": 0.25,
                "geopolitical_risk": 0.40,
                "macro_risk": 0.20,
                "company_specific_risk": 0.15,
            }
        if regime == "elevated":
            return {
                "sector_risk": 0.30,
                "geopolitical_risk": 0.30,
                "macro_risk": 0.20,
                "company_specific_risk": 0.20,
            }
        return dict(self.weights)

    @staticmethod
    def _cap_class(market_cap: Optional[float]) -> str:
        if market_cap is None:
            return "unknown"
        if market_cap >= 500e9:
            return "large"
        if market_cap >= 50e9:
            return "mid"
        return "small"

    @staticmethod
    def _cap_multiplier(cap_class: str) -> float:
        mapping = {"large": 0.85, "mid": 1.0, "small": 1.25, "unknown": 1.0}
        return mapping.get(cap_class, 1.0)

    @staticmethod
    def _contagion_boost(
        db_session: Any,
        instrument_id: int,
        sector: Optional[str],
        current_date: datetime,
    ) -> float:
        """Spillover from same-sector peers with high risk."""
        from src.db.models import CompanyRiskHistory, Instrument
        if not sector:
            return 0.0
        peers = (
            db_session.query(CompanyRiskHistory)
            .join(Instrument, Instrument.id == CompanyRiskHistory.instrument_id)
            .filter(
                Instrument.sector == sector,
                Instrument.id != instrument_id,
                CompanyRiskHistory.date == current_date.date(),
                CompanyRiskHistory.risk_score >= 6.0,
            )
            .all()
        )
        if not peers:
            return 0.0
        avg_peer_risk = sum(p.risk_score for p in peers) / len(peers)
        excess = avg_peer_risk - 6.0  # how far above threshold
        return max(0.0, excess * CONTAGION_COEFFICIENT)

    # ── Component calculators ────────────────────────────────────────────────

    def calculate_sector_risk_component(
        self,
        instrument: Any,
        db_session: Any,
        current_date: Optional[datetime] = None,
    ) -> float:
        from src.db.models import SectorRiskHistory
        if current_date is None:
            current_date = datetime.utcnow()
        if not instrument.sector:
            return self._get_sector_baseline(None)
        sector_risk = (
            db_session.query(SectorRiskHistory)
            .filter(
                SectorRiskHistory.sector == instrument.sector,
                SectorRiskHistory.date == current_date.date(),
            )
            .first()
        )
        return sector_risk.risk_score if sector_risk else self._get_sector_baseline(instrument.sector)

    def calculate_geopolitical_risk_component(
        self,
        db_session: Any,
        current_date: Optional[datetime] = None,
    ) -> float:
        from src.db.models import GeopoliticalRiskHistory
        if current_date is None:
            current_date = datetime.utcnow()
        geo_risk = (
            db_session.query(GeopoliticalRiskHistory)
            .filter(GeopoliticalRiskHistory.date == current_date.date())
            .first()
        )
        return geo_risk.risk_score if geo_risk else 5.0

    def calculate_macro_risk_component(
        self,
        db_session: Any,
        current_date: Optional[datetime] = None,
    ) -> float:
        from src.db.models import NewsCompanyImpact
        if current_date is None:
            current_date = datetime.utcnow()
        macro_impacts = (
            db_session.query(NewsCompanyImpact)
            .filter(
                NewsCompanyImpact.impact_type == "monetary",
                NewsCompanyImpact.created_at >= current_date - timedelta(days=30),
            )
            .all()
        )
        if not macro_impacts:
            return 5.0
        avg_impact = sum(m.impact_score for m in macro_impacts) / len(macro_impacts)
        return min(10.0, avg_impact)

    def calculate_company_specific_risk_component(
        self,
        instrument: Any,
        db_session: Any,
        current_date: Optional[datetime] = None,
    ) -> float:
        from src.db.models import NewsCompanyImpact
        if current_date is None:
            current_date = datetime.utcnow()
        company_impacts = (
            db_session.query(NewsCompanyImpact)
            .filter(
                NewsCompanyImpact.instrument_id == instrument.id,
                NewsCompanyImpact.impact_type == "company_specific",
                NewsCompanyImpact.created_at >= current_date - timedelta(days=30),
            )
            .all()
        )
        if not company_impacts:
            return 0.0
        avg_impact = sum(m.impact_score for m in company_impacts) / len(company_impacts)
        return min(10.0, avg_impact)

    # ── Sentiment / recency ─────────────────────────────────────────────────

    def _sentiment_multiplier(
        self, db_session: Any, instrument_id: int, current_date: datetime
    ) -> float:
        from src.db.models import News, NewsInstrument
        recent_news = (
            db_session.query(News)
            .join(NewsInstrument, NewsInstrument.news_id == News.id)
            .filter(
                NewsInstrument.instrument_id == instrument_id,
                News.published_at >= current_date - timedelta(days=30),
            )
            .all()
        )
        if not recent_news:
            return 1.0
        negative_count = sum(1 for n in recent_news if n.sentiment == "negative")
        ratio = negative_count / len(recent_news)
        return 0.8 + ratio * 0.4

    def _recency_boost(
        self, db_session: Any, instrument_id: int, current_date: datetime
    ) -> float:
        from src.db.models import NewsCompanyImpact
        recent = (
            db_session.query(NewsCompanyImpact)
            .filter(
                NewsCompanyImpact.instrument_id == instrument_id,
                NewsCompanyImpact.created_at >= current_date - timedelta(days=7),
            )
            .count()
        )
        return 1.0 + min(0.2, recent * 0.02)

    @staticmethod
    def _confidence(has_geo: bool, has_sector: bool, has_company: bool, has_prices: bool, has_cap: bool) -> float:
        score = 0.0
        if has_geo:
            score += 0.20
        if has_sector:
            score += 0.20
        if has_company:
            score += 0.25
        if has_prices:
            score += 0.20
        if has_cap:
            score += 0.15
        return score

    # ── Main API ─────────────────────────────────────────────────────────────

    def calculate_company_risk(
        self,
        instrument: Any,
        db_session: Any,
        current_date: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if current_date is None:
            current_date = datetime.utcnow()

        from src.db.models import FundamentalMetric, News, NewsInstrument

        regime = self._get_market_regime(db_session)
        active_weights = self._adjust_weights(regime)

        sector_risk = self.calculate_sector_risk_component(instrument, db_session, current_date)
        geo_risk = self.calculate_geopolitical_risk_component(db_session, current_date)
        macro_risk = self.calculate_macro_risk_component(db_session, current_date)
        company_risk = self.calculate_company_specific_risk_component(instrument, db_session, current_date)

        # Volatility
        vol_score = self._compute_volatility(db_session, instrument.id)
        vol_contribution = vol_score * 0.10  # 10% vol weight baked in

        # Contagion
        contagion = self._contagion_boost(db_session, instrument.id, instrument.sector, current_date)

        # Cap class
        fm = (
            db_session.query(FundamentalMetric)
            .filter(FundamentalMetric.instrument_id == instrument.id)
            .order_by(FundamentalMetric.date.desc())
            .first()
        )
        cap_class_str = "unknown"
        if fm and fm.market_cap:
            cap_class_str = self._cap_class(fm.market_cap)
        cap_mult = self._cap_multiplier(cap_class_str)

        # Weighted base score
        base = (
            sector_risk * active_weights["sector_risk"]
            + geo_risk * active_weights["geopolitical_risk"]
            + macro_risk * active_weights["macro_risk"]
            + company_risk * active_weights["company_specific_risk"]
        )

        # Apply adjustments
        sentiment_mult = self._sentiment_multiplier(db_session, instrument.id, current_date)
        recency = self._recency_boost(db_session, instrument.id, current_date)
        final_risk = (base + vol_contribution + contagion) * sentiment_mult * recency * cap_mult
        final_risk = min(10.0, max(0.0, final_risk))

        # Confidence
        conf = self._confidence(
            has_geo=geo_risk > 0,
            has_sector=sector_risk > 0,
            has_company=company_risk > 0,
            has_prices=vol_score != 5.0 or bool(
                db_session.query(FundamentalMetric)
                .filter(FundamentalMetric.instrument_id == instrument.id)
                .first()
            ),
            has_cap=cap_class_str != "unknown",
        )

        return {
            "instrument_id": instrument.id,
            "ticker": instrument.ticker,
            "date": current_date.date(),
            "risk_score": round(final_risk, 2),
            "regime": regime,
            "decomposition": {
                "sector_risk": round(sector_risk, 2),
                "geopolitical_risk": round(geo_risk, 2),
                "macro_risk": round(macro_risk, 2),
                "company_specific_risk": round(company_risk, 2),
                "volatility_contribution": round(vol_contribution, 2),
                "contagion_contribution": round(contagion, 2),
            },
            "adjustments": {
                "regime_weights": active_weights,
                "sentiment_multiplier": round(sentiment_mult, 3),
                "recency_multiplier": round(recency, 3),
                "cap_class": cap_class_str,
                "cap_multiplier": round(cap_mult, 3),
            },
            "confidence": round(conf, 2),
            "recent_news_count": (
                db_session.query(News)
                .join(NewsInstrument, NewsInstrument.news_id == News.id)
                .filter(
                    NewsInstrument.instrument_id == instrument.id,
                    News.published_at >= current_date - timedelta(days=30),
                )
                .count()
            ),
        }

    def batch_calculate_company_risks(
        self,
        instruments: list[Any],
        db_session: Any,
        current_date: Optional[datetime] = None,
    ) -> dict[int, dict[str, Any]]:
        return {
            inst.id: self.calculate_company_risk(inst, db_session, current_date)
            for inst in instruments
        }

    def store_company_risk(self, company_risk: dict[str, Any], db_session: Any) -> bool:
        from src.db.models import CompanyRiskHistory
        try:
            record = CompanyRiskHistory(
                instrument_id=company_risk["instrument_id"],
                date=company_risk["date"],
                risk_score=company_risk["risk_score"],
                sector_risk=company_risk["decomposition"]["sector_risk"],
                geopolitical_risk=company_risk["decomposition"]["geopolitical_risk"],
                macro_risk=company_risk["decomposition"]["macro_risk"],
                company_specific_risk=company_risk["decomposition"]["company_specific_risk"],
                components_json=company_risk,
                article_count=company_risk.get("recent_news_count", 0),
            )
            db_session.add(record)
            db_session.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to store company risk for {company_risk.get('ticker')}: {e}")
            return False

    def get_high_risk_companies(
        self,
        db_session: Any,
        threshold: float = 6.5,
        count: int = 20,
    ) -> list[dict[str, Any]]:
        from src.db.models import CompanyRiskHistory, Instrument
        today = datetime.utcnow().date()
        high_risk = (
            db_session.query(CompanyRiskHistory)
            .filter(
                CompanyRiskHistory.date == today,
                CompanyRiskHistory.risk_score >= threshold,
            )
            .order_by(CompanyRiskHistory.risk_score.desc())
            .limit(count)
            .all()
        )
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
        self,
        instrument: Any,
        db_session: Any,
        days: int = 30,
    ) -> dict[str, Any]:
        from src.db.models import CompanyRiskHistory
        history = (
            db_session.query(CompanyRiskHistory)
            .filter(
                CompanyRiskHistory.instrument_id == instrument.id,
                CompanyRiskHistory.date >= datetime.utcnow().date() - timedelta(days=days),
            )
            .order_by(CompanyRiskHistory.date)
            .all()
        )
        if not history:
            return {
                "ticker": instrument.ticker,
                "trend": "no_data",
                "current_risk": 0.0,
                "average_risk": 0.0,
            }
        scores = [h.risk_score for h in history]
        current = scores[-1]
        average = sum(scores) / len(scores)
        if len(scores) > 1:
            trend = "up" if scores[-1] > scores[0] else "down"
        else:
            trend = "flat"
        return {
            "ticker": instrument.ticker,
            "trend": trend,
            "current_risk": current,
            "average_risk": round(average, 2),
            "history": [{"date": h.date, "risk": h.risk_score} for h in history],
        }

    def get_portfolio_risk(
        self,
        instrument_ids: list[int],
        db_session: Any,
        current_date: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Aggregate risk across a portfolio of instruments."""
        from src.db.models import CompanyRiskHistory
        if current_date is None:
            current_date = datetime.utcnow()
        date = current_date.date()
        risks = (
            db_session.query(CompanyRiskHistory)
            .filter(
                CompanyRiskHistory.instrument_id.in_(instrument_ids),
                CompanyRiskHistory.date == date,
            )
            .all()
        )
        if not risks:
            return {"portfolio_risk": 0.0, "instruments": 0, "max_risk": 0.0}
        scores = [r.risk_score for r in risks]
        return {
            "portfolio_risk": round(sum(scores) / len(scores), 2),
            "instruments": len(scores),
            "max_risk": round(max(scores), 2),
            "min_risk": round(min(scores), 2),
            "high_risk_count": sum(1 for s in scores if s >= 6.5),
        }
