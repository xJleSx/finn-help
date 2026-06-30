from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import GeoRiskScore, MarketEvent

logger = logging.getLogger(__name__)


class EventFeatureBuilder:
    def build_features(self, events: list[MarketEvent], dates: pd.Series) -> pd.DataFrame:
        if not events:
            result = pd.DataFrame(
                {
                    "date": pd.to_datetime(dates),
                    "event_count_30d": 0,
                    "event_severity_30d": 0.0,
                    "sanctions_30d": 0,
                    "days_since_major_event": 999,
                    "is_anomaly": False,
                }
            )
            result["date"] = result["date"].astype(object)
            return result

        ev_df = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp(str(e.date)),
                    "impact": abs(e.market_impact_pct or 0),
                    "is_sanctions": e.event_type == "sanctions_timeline",
                }
                for e in events
            ]
        )
        ev_df = ev_df.sort_values("date")
        result_rows = []
        for d in pd.to_datetime(dates):
            cutoff = d - pd.Timedelta(days=30)
            window = ev_df[(ev_df["date"] >= cutoff) & (ev_df["date"] < d)]
            count = len(window)
            severity = float(window["impact"].mean()) if count > 0 else 0.0
            sanctions = int(window["is_sanctions"].sum()) if count > 0 else 0
            major = ev_df[ev_df["impact"] > 2.0]
            if not major.empty and major["date"].max() < d:
                days_since = (d - major["date"].max()).days
            else:
                days_since = 999
            result_rows.append(
                {
                    "date": d,
                    "event_count_30d": count,
                    "event_severity_30d": severity,
                    "sanctions_30d": sanctions,
                    "days_since_major_event": days_since,
                    "is_anomaly": days_since < 3,
                }
            )
        result = pd.DataFrame(result_rows)
        result["date"] = pd.to_datetime(result["date"])
        result["date"] = result["date"].astype(object)
        return result

    async def compute_geo_from_events(self, db: AsyncSession) -> float | None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        result = await db.execute(
            select(MarketEvent).where(MarketEvent.event_type == "sanctions_timeline", MarketEvent.date >= cutoff)
        )
        events = result.scalars().all()
        if not events:
            return None

        now = datetime.now(timezone.utc).date()
        score = 2.0
        for e in events:
            if e.date >= now - timedelta(days=7):
                score += 1.0
            else:
                score += 0.5
            if e.severity and e.severity > 0.8:
                score += 0.5
        score = min(score, 10.0)
        return round(score, 1)

    def compute_geo_from_events_sync(self, db: Any) -> float | None:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
        events = (
            db.query(MarketEvent)
            .filter(MarketEvent.event_type == "sanctions_timeline", MarketEvent.date >= cutoff)
            .all()
        )
        if not events:
            return None

        now = datetime.now(timezone.utc).date()
        score = 2.0
        for e in events:
            if e.date >= now - timedelta(days=7):
                score += 1.0
            else:
                score += 0.5
            if e.severity and e.severity > 0.8:
                score += 0.5
        score = min(score, 10.0)
        return round(score, 1)

    async def load_geo(self, db: AsyncSession) -> dict[str, Any]:
        score = await self.compute_geo_from_events(db)
        if score is not None:
            return {"score": score}
        result = await db.execute(select(GeoRiskScore).order_by(GeoRiskScore.date.desc()).limit(1))
        geo = result.scalar_one_or_none()
        return {"score": geo.score} if geo else {"score": 0.0}

    def load_geo_sync(self, db: Any) -> dict[str, Any]:
        geo_val = self.compute_geo_from_events_sync(db)
        if geo_val is None:
            geo_row = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
            geo_val = geo_row.score if geo_row else 0.0
        return {"score": geo_val}

    async def load_market_events(self, db: AsyncSession, days: int = 30) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await db.execute(select(MarketEvent).where(MarketEvent.date >= cutoff))
        events = result.scalars().all()
        if not events:
            return {
                "event_risk_score": 0.0,
                "sanctions_spike": False,
                "recent_types": [],
                "event_count": 0,
                "total_impact": 0.0,
                "recent_for_llm": [],
            }

        high_impact = sum(1 for e in events if e.market_impact_pct is not None and abs(e.market_impact_pct) > 1.5)
        trading_days = max(len(events), 1)
        event_risk_score = min(high_impact / trading_days, 1.0)

        recent_cutoff = datetime.now(timezone.utc).date() - timedelta(days=7)
        recent = [e for e in events if e.date >= recent_cutoff]
        sanctions_spike = any(getattr(e, "event_type", "") == "sanctions_timeline" for e in recent)
        recent_types = list({getattr(e, "event_type", "") for e in recent})[:5]

        total_impact = sum(abs(e.market_impact_pct or 0) for e in events)
        total_impact = min(total_impact / 100.0, 1.0)

        recent_for_llm = []
        for e in sorted(recent, key=lambda x: x.date, reverse=True)[:5]:
            impact = f" ({e.market_impact_pct:+.1f}%)" if e.market_impact_pct else ""
            recent_for_llm.append(f"{e.date} — {e.event_type}: {e.title}{impact}")

        return {
            "event_risk_score": round(event_risk_score, 3),
            "sanctions_spike": sanctions_spike,
            "recent_types": recent_types,
            "event_count": len(events),
            "total_impact": round(total_impact, 3),
            "recent_for_llm": recent_for_llm,
        }

    def load_market_events_sync(self, db: Any, days: int = 30) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
        events = db.query(MarketEvent).filter(MarketEvent.date >= cutoff).all()
        if not events:
            return {
                "event_risk_score": 0.0,
                "sanctions_spike": False,
                "recent_types": [],
                "event_count": 0,
                "total_impact": 0.0,
            }

        high_impact = sum(1 for e in events if e.market_impact_pct is not None and abs(e.market_impact_pct) > 1.5)
        trading_days = max(len(events), 1)
        event_risk_score = min(high_impact / trading_days, 1.0)

        recent_cutoff = datetime.now(timezone.utc).date() - timedelta(days=7)
        recent = [e for e in events if e.date >= recent_cutoff]
        sanctions_spike = any(getattr(e, "event_type", "") == "sanctions_timeline" for e in recent)
        recent_types = list({getattr(e, "event_type", "") for e in recent})[:5]

        total_impact = sum(abs(e.market_impact_pct or 0) for e in events)
        total_impact = min(total_impact / 100.0, 1.0)

        return {
            "event_risk_score": round(event_risk_score, 3),
            "sanctions_spike": sanctions_spike,
            "recent_types": recent_types,
            "event_count": len(events),
            "total_impact": round(total_impact, 3),
        }

    async def load_all_events(self, db: AsyncSession) -> list[MarketEvent]:
        result = await db.execute(select(MarketEvent).order_by(MarketEvent.date))
        return list(result.scalars().all())

    def load_all_events_sync(self, db: Any) -> list[MarketEvent]:
        return list(db.query(MarketEvent).order_by(MarketEvent.date).all())


event_features = EventFeatureBuilder()
