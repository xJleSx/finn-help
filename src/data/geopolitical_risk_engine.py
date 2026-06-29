"""Geopolitical Risk Engine v2 — EWMA, events, sector mapping, forward projection.

Includes:
  - Sanctions (35%), conflict (30%), trade war (20%), diplomacy (15%)
  - EWMA score smoothing across history
  - Individual event detection with severity scoring
  - Sector-level impact mapping
  - Forward-looking projection (7d / 30d velocity)
  - Regional & country entity extraction
  - Confidence interval
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

GEO_RISK_WEIGHTS = {
    "sanctions": 0.35,
    "conflict": 0.30,
    "trade_war": 0.20,
    "diplomacy": 0.15,
}

REGIONAL_MULTIPLIERS: dict[str, float] = {
    "russia": 1.2,
    "china": 1.1,
    "europe": 0.9,
    "usa": 0.8,
    "middle_east": 1.0,
    "asia": 1.0,
    "africa": 0.9,
    "latin_america": 0.9,
}

REGION_KEYWORDS: dict[str, list[str]] = {
    "russia": ["россия", "russian", "рф", "кремль", "москва", "moscow", "putin", "путин"],
    "china": ["china", "chinese", "китай", "пекин", "beijing", "xi jinping", "си"],
    "europe": ["европа", "european", "евросоюз", "eu", "брюссель", "brussels", "нато", "nato"],
    "usa": ["usa", "united states", "washington", "сша", "америка", "biden", "байден", "trump"],
    "middle_east": ["middle east", "иран", "iran", "саудовская аравия", "saudi", "израиль", "israel"],
    "asia": ["india", "индия", "japan", "япония", "korea", "корея", "taiwan", "тайвань"],
    "africa": ["africa", "африка", "south africa", "юар"],
    "latin_america": ["latin america", "бразилия", "brazil", "латинская америка"],
}

# Known event templates for pattern matching
EVENT_PATTERNS: list[dict[str, Any]] = [
    {"pattern": r"санкци[яи] (против|на|в отношении)", "category": "sanctions", "base_severity": 7.0},
    {"pattern": r"новы[ех] санкци[яи]", "category": "sanctions", "base_severity": 8.0},
    {"pattern": r"военн[аы]х? действи[яй]", "category": "conflict", "base_severity": 9.0},
    {"pattern": r"атак[аи]|удар[а]?|обстрел", "category": "conflict", "base_severity": 8.0},
    {"pattern": r"конфликт|войн[аы]", "category": "conflict", "base_severity": 8.0},
    {"pattern": r"торгов[ая]? войн[аы]?", "category": "trade_war", "base_severity": 6.0},
    {"pattern": r"пошлин[аы]|тариф[а]?|эмбарго", "category": "trade_war", "base_severity": 5.0},
    {"pattern": r"переговор[аы]|договор[а]?", "category": "diplomacy", "base_severity": 3.0},
    {"pattern": r"саммит|визит|встреч[аи]", "category": "diplomacy", "base_severity": 2.0},
    {"pattern": r"санкци[яи] против (росси[яи]|рф)", "category": "sanctions", "base_severity": 9.0},
    {"pattern": r"заморозк[аи] активов", "category": "sanctions", "base_severity": 7.0},
]

# Sector sensitivity to geopolitical subcategories
SECTOR_GEO_SENSITIVITY: dict[str, dict[str, float]] = {
    "Нефть": {"sanctions": 1.4, "conflict": 1.3, "trade_war": 1.2, "diplomacy": 0.8},
    "Металлы": {"sanctions": 1.3, "conflict": 1.2, "trade_war": 1.3, "diplomacy": 0.8},
    "Финансы": {"sanctions": 1.2, "conflict": 1.0, "trade_war": 1.1, "diplomacy": 0.9},
    "IT": {"sanctions": 0.9, "conflict": 0.8, "trade_war": 1.2, "diplomacy": 0.7},
    "Телеком": {"sanctions": 1.0, "conflict": 0.9, "trade_war": 0.9, "diplomacy": 0.7},
    "Энергетика": {"sanctions": 1.1, "conflict": 1.3, "trade_war": 1.0, "diplomacy": 0.8},
    "Транспорт": {"sanctions": 1.0, "conflict": 1.1, "trade_war": 1.1, "diplomacy": 0.8},
    "Потребтовары": {"sanctions": 0.8, "conflict": 0.9, "trade_war": 1.3, "diplomacy": 0.7},
    "Строительство": {"sanctions": 0.7, "conflict": 0.8, "trade_war": 0.8, "diplomacy": 0.6},
    "Химия": {"sanctions": 1.1, "conflict": 1.0, "trade_war": 1.1, "diplomacy": 0.8},
    "Машиностроение": {"sanctions": 1.2, "conflict": 1.1, "trade_war": 1.2, "diplomacy": 0.8},
}

EWMA_ALPHA = 0.3  # smoothing factor for historical scores


class DetectedEvent:
    """Represents a detected geopolitical event from news."""

    def __init__(self, category: str, severity: float, region: Optional[str], snippet: str, date: datetime):
        self.category = category
        self.severity = severity
        self.region = region
        self.snippet = snippet
        self.date = date

    def decayed_severity(self, reference_date: datetime) -> float:
        days = (reference_date - self.date).days
        if days <= 0:
            return self.severity
        return self.severity * (0.5 ** (days / 30))


class GeopoliticalRiskEngine:
    """Calculates comprehensive geopolitical risk scores with EWMA, events, and sector impact."""

    def __init__(self):
        self.weights = GEO_RISK_WEIGHTS
        self.regional_multipliers = REGIONAL_MULTIPLIERS
        self.ewma_alpha = EWMA_ALPHA

    # ── Entity extraction ───────────────────────────────────────────────────

    def extract_region_from_news(self, title: str, summary: str) -> Optional[str]:
        text = f"{title} {summary}".lower()
        for region, keywords in REGION_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return region
        return None

    def extract_countries(self, title: str, summary: str) -> list[str]:
        text = f"{title} {summary}".lower()
        found = []
        for region, keywords in REGION_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                found.append(region)
        return found

    # ── Event detection ─────────────────────────────────────────────────────

    def detect_events(self, articles: list[Any]) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        for article in articles:
            text = f"{article.title or ''} {article.summary or ''}".lower()
            region = self.extract_region_from_news(article.title or "", article.summary or "")
            for template in EVENT_PATTERNS:
                if re.search(template["pattern"], text, re.IGNORECASE):
                    event = DetectedEvent(
                        category=template["category"],
                        severity=template["base_severity"],
                        region=region,
                        snippet=text[:120],
                        date=article.published_at or datetime.utcnow(),
                    )
                    events.append(event)
                    break
        return events

    def calculate_event_risk(
        self, events: list[DetectedEvent], current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        if current_date is None:
            current_date = datetime.utcnow()

        category_scores: dict[str, float] = defaultdict(float)
        for event in events:
            cat = event.category
            category_scores[cat] += event.decayed_severity(current_date)

        # Normalise per category (cap at 10)
        for cat in category_scores:
            category_scores[cat] = min(10.0, category_scores[cat])

        return dict(category_scores)

    # ── Subcategory score ───────────────────────────────────────────────────

    def calculate_subcategory_score(
        self, subcategory: str, articles: list[Any], current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        if current_date is None:
            current_date = datetime.utcnow()

        relevant = [a for a in articles if a.is_relevant and a.subcategory == subcategory]

        if not relevant:
            return {"subcategory": subcategory, "risk_score": 0.0, "article_count": 0, "sources": set()}

        total_risk = 0.0
        sources: set[str] = set()

        for article in relevant:
            days_old = (current_date - (article.published_at or current_date)).days
            decay = 0.5 ** (days_old / 30)
            sentiment_mult = 1.0
            if article.sentiment == "positive":
                sentiment_mult = 0.7
            elif article.sentiment == "negative":
                sentiment_mult = 1.3
            impact = (article.impact_score or 5) * decay * sentiment_mult
            total_risk += impact
            if article.source_name:
                sources.add(article.source_name)

        avg_risk = min(10.0, total_risk / len(relevant))

        return {
            "subcategory": subcategory,
            "risk_score": avg_risk,
            "article_count": len(relevant),
            "sources": sources,
            "source_count": len(sources),
        }

    # ── Sector impact ───────────────────────────────────────────────────────

    def sector_geo_multiplier(self, sector: str, subcategory_scores: dict[str, float]) -> dict[str, float]:
        base = SECTOR_GEO_SENSITIVITY.get(sector, {})
        impact: dict[str, float] = {}
        for subcat, score in subcategory_scores.items():
            sensitivity = base.get(subcat, 1.0)
            impact[subcat] = min(10.0, score * sensitivity)
        return impact

    # ── EWMA smoothing ──────────────────────────────────────────────────────

    @staticmethod
    def compute_ewma(history: list[float], alpha: float = EWMA_ALPHA) -> float:
        if not history:
            return 0.0
        smoothed = history[0]
        for val in history[1:]:
            smoothed = alpha * val + (1 - alpha) * smoothed
        return smoothed

    # ── Forward projection ──────────────────────────────────────────────────

    @staticmethod
    def forward_projection(history: list[float], days_forward: int = 30) -> float:
        if len(history) < 3:
            return history[-1] if history else 0.0
        x = list(range(len(history)))
        y = history
        n = len(x)
        slope = (n * sum(a * b for a, b in zip(x, y)) - sum(x) * sum(y)) / (
            n * sum(a ** 2 for a in x) - sum(x) ** 2
        )
        return max(0.0, min(10.0, history[-1] + slope * days_forward))

    # ── Daily calculation ───────────────────────────────────────────────────

    def calculate_daily_geopolitical_risk(
        self, db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        from src.db.models import GeopoliticalRiskHistory, News

        if current_date is None:
            current_date = datetime.utcnow()

        geo_articles = (
            db_session.query(News)
            .filter(
                News.category == "GEOPOLITICAL",
                News.is_relevant,
                News.published_at >= current_date - timedelta(days=90),
            )
            .all()
        )

        if not geo_articles:
            return {
                "date": current_date.date(),
                "risk_score": 0.0,
                "subcategories": {},
                "article_count": 0,
                "sources": [],
                "events": [],
                "ewma_score": 0.0,
                "forward_7d": 0.0,
                "forward_30d": 0.0,
                "confidence": 0.0,
            }

        # News-based subcategory scores
        subcategories = {}
        all_sources: set[str] = set()
        total_weighted = 0.0

        for subcat, weight in self.weights.items():
            result = self.calculate_subcategory_score(subcat, geo_articles, current_date)
            subcategories[subcat] = {
                "risk_score": result["risk_score"],
                "article_count": result["article_count"],
            }
            all_sources.update(result["sources"])
            total_weighted += result["risk_score"] * weight

        overall = min(10.0, total_weighted)

        # Source diversity
        source_div = min(1.0, len(all_sources) / 10.0)
        diversity_mult = 0.8 + source_div * 0.4
        news_score = min(10.0, overall * diversity_mult)

        # Event detection
        events = self.detect_events(geo_articles)
        event_category_scores = self.calculate_event_risk(events, current_date)
        event_score = (
            sum(
                event_category_scores.get(cat, 0.0) * self.weights.get(cat, 0.0)
                for cat in self.weights
            )
            * 0.3  # event component weighted at 30% of total
        )
        event_score = min(10.0, event_score)

        # Blend news score + event score
        blended = news_score * 0.7 + event_score * 0.3

        # EWMA from history
        history_records = (
            db_session.query(GeopoliticalRiskHistory)
            .filter(
                GeopoliticalRiskHistory.date >= current_date.date() - timedelta(days=60),
                GeopoliticalRiskHistory.date < current_date.date(),
            )
            .order_by(GeopoliticalRiskHistory.date)
            .all()
        )
        history_scores = [h.risk_score for h in history_records]

        ewma_score = self.compute_ewma(history_scores + [blended]) if history_scores else blended
        forward_7d = self.forward_projection(history_scores + [blended], 7)
        forward_30d = self.forward_projection(history_scores + [blended], 30)

        final_risk = ewma_score

        # Confidence
        article_conf = min(1.0, len(geo_articles) / 50)
        source_conf = min(1.0, len(all_sources) / 5)
        history_conf = min(1.0, len(history_scores) / 30)
        confidence = article_conf * 0.4 + source_conf * 0.3 + history_conf * 0.3

        # Event summaries
        event_summaries = [
            {"category": e.category, "severity": round(e.severity, 1), "region": e.region, "date": e.date.isoformat()}
            for e in events[:20]
        ]

        return {
            "date": current_date.date(),
            "risk_score": round(final_risk, 2),
            "ewma_score": round(ewma_score, 2),
            "news_score": round(news_score, 2),
            "event_score": round(event_score, 2),
            "forward_7d": round(forward_7d, 2),
            "forward_30d": round(forward_30d, 2),
            "confidence": round(confidence, 2),
            "subcategories": {
                cat: subcategories.get(cat, {"risk_score": 0.0, "article_count": 0})
                for cat in ["sanctions", "conflict", "trade_war", "diplomacy"]
            },
            "total_article_count": len(geo_articles),
            "unique_sources": len(all_sources),
            "source_diversity_score": round(source_div, 2),
            "events": event_summaries,
            "event_count": len(events),
        }

    # ── Trend ───────────────────────────────────────────────────────────────

    def calculate_geopolitical_trend(self, db_session: Any, days: int = 30) -> dict[str, Any]:
        from src.db.models import GeopoliticalRiskHistory

        history = (
            db_session.query(GeopoliticalRiskHistory)
            .filter(
                GeopoliticalRiskHistory.date >= datetime.utcnow().date() - timedelta(days=days)
            )
            .order_by(GeopoliticalRiskHistory.date)
            .all()
        )

        if not history:
            return {
                "trend": "no_data",
                "current_risk": 0.0,
                "average_risk": 0.0,
                "max_risk": 0.0,
                "ewma": 0.0,
                "volatility": 0.0,
            }

        scores = [h.risk_score for h in history]
        current = scores[-1]
        average = sum(scores) / len(scores)
        max_risk = max(scores)
        ewma_val = self.compute_ewma(scores)

        # Volatility of scores
        if len(scores) > 1:
            volatility = float(np.std(scores)) if len(scores) > 1 else 0.0
        else:
            volatility = 0.0

        scores_float = scores

        if len(scores) > 1:
            trend_dir = "up" if scores_float[-1] > scores_float[0] else "down"
            trend_mag = abs(scores_float[-1] - scores_float[0])
        else:
            trend_dir = "flat"
            trend_mag = 0.0

        if len(scores) > 1:
            x = list(range(len(scores)))
            n = len(x)
            slope = (n * sum(a * b for a, b in zip(x, scores_float)) - sum(x) * sum(scores_float)) / (
                n * sum(a ** 2 for a in x) - sum(x) ** 2
            )
            velocity = slope
        else:
            velocity = 0.0

        return {
            "period_days": days,
            "trend": trend_dir,
            "trend_magnitude": min(10.0, trend_mag),
            "trend_velocity": round(velocity, 4),
            "current_risk": current,
            "average_risk": round(average, 2),
            "max_risk": max_risk,
            "ewma": round(ewma_val, 2),
            "volatility": round(volatility, 2),
            "history": [{"date": h.date, "risk": h.risk_score} for h in history],
        }

    # ── Store ───────────────────────────────────────────────────────────────

    def store_geopolitical_risk(self, geo_risk: dict[str, Any], db_session: Any) -> bool:
        from src.db.models import GeopoliticalRiskHistory

        try:
            record = GeopoliticalRiskHistory(
                date=geo_risk["date"],
                risk_score=geo_risk["risk_score"],
                sanctions_score=geo_risk["subcategories"]["sanctions"]["risk_score"],
                conflict_score=geo_risk["subcategories"]["conflict"]["risk_score"],
                trade_war_score=geo_risk["subcategories"]["trade_war"]["risk_score"],
                diplomacy_score=geo_risk["subcategories"]["diplomacy"]["risk_score"],
                components_json={
                    "ewma_score": geo_risk.get("ewma_score"),
                    "news_score": geo_risk.get("news_score"),
                    "event_score": geo_risk.get("event_score"),
                    "forward_7d": geo_risk.get("forward_7d"),
                    "forward_30d": geo_risk.get("forward_30d"),
                    "confidence": geo_risk.get("confidence"),
                    "event_count": geo_risk.get("event_count"),
                },
                sources_json={
                    "unique_sources": geo_risk["unique_sources"],
                    "source_diversity": geo_risk.get("source_diversity_score"),
                },
                article_count=geo_risk["total_article_count"],
            )
            db_session.add(record)
            db_session.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to store geopolitical risk: {e}")
            return False

    # ── Alert level ─────────────────────────────────────────────────────────

    @staticmethod
    def get_risk_alert_level(risk_score: float) -> str:
        if risk_score < 3:
            return "low"
        if risk_score < 5:
            return "medium"
        if risk_score < 7:
            return "high"
        return "critical"

    # ── Emerging threats ────────────────────────────────────────────────────

    def identify_emerging_threats(self, db_session: Any, sensitivity: float = 0.2) -> list[dict[str, Any]]:
        from src.db.models import GeopoliticalRiskHistory

        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)

        today_rec = (
            db_session.query(GeopoliticalRiskHistory).filter(GeopoliticalRiskHistory.date == today).first()
        )
        yesterday_rec = (
            db_session.query(GeopoliticalRiskHistory).filter(GeopoliticalRiskHistory.date == yesterday).first()
        )
        week_rec = (
            db_session.query(GeopoliticalRiskHistory).filter(GeopoliticalRiskHistory.date == week_ago).first()
        )

        threats = []

        if today_rec and yesterday_rec:
            day_change = today_rec.risk_score - yesterday_rec.risk_score
            if day_change > sensitivity * 10:
                threats.append({
                    "type": "spike",
                    "magnitude": round(day_change, 2),
                    "period": "1_day",
                    "current_level": today_rec.risk_score,
                })

        if today_rec and week_rec:
            week_change = today_rec.risk_score - week_rec.risk_score
            if week_change > sensitivity * 10:
                threats.append({
                    "type": "trend",
                    "magnitude": round(week_change, 2),
                    "period": "7_days",
                    "current_level": today_rec.risk_score,
                })

        return threats

    # ── Sector geo impact ───────────────────────────────────────────────────

    def sector_geo_impact(
        self, sector: str, db_session: Any, current_date: Optional[datetime] = None
    ) -> dict[str, Any]:
        if current_date is None:
            current_date = datetime.utcnow()

        risk = self.calculate_daily_geopolitical_risk(db_session, current_date)
        subcat_scores = {k: v["risk_score"] for k, v in risk["subcategories"].items()}
        sector_adjusted = self.sector_geo_multiplier(sector, subcat_scores)
        avg_adjusted = sum(sector_adjusted.values()) / len(sector_adjusted) if sector_adjusted else 0.0

        return {
            "sector": sector,
            "base_geo_risk": risk["risk_score"],
            "adjusted_risk": round(avg_adjusted, 2),
            "subcategory_breakdown": sector_adjusted,
        }

    # ── Market impact assessment ────────────────────────────────────────────

    def market_impact_assessment(self, db_session: Any, current_date: Optional[datetime] = None) -> dict[str, Any]:
        risk = self.calculate_daily_geopolitical_risk(db_session, current_date)
        alert = self.get_risk_alert_level(risk["risk_score"])
        threats = self.identify_emerging_threats(db_session)

        sectors = list(SECTOR_GEO_SENSITIVITY.keys())
        sector_impacts = {
            s: self.sector_geo_impact(s, db_session, current_date)
            for s in sectors
        }
        most_affected = sorted(sector_impacts.items(), key=lambda x: x[1]["adjusted_risk"], reverse=True)[:3]

        return {
            "date": risk["date"],
            "overall_risk": risk["risk_score"],
            "alert_level": alert,
            "forward_7d": risk.get("forward_7d"),
            "forward_30d": risk.get("forward_30d"),
            "confidence": risk.get("confidence"),
            "threats": threats,
            "most_affected_sectors": [
                {"sector": s[0], "adjusted_risk": s[1]["adjusted_risk"]} for s in most_affected
            ],
        }
