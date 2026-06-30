from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.collectors.macro import MacroCollector
from src.constants import NEWS_SENTIMENT_DAYS
from src.db.models import (
    BondOffering,
    Dividend,
    FinancialReport,
    FundamentalMetric,
    GeoRiskScore,
    Instrument,
    MetricSnapshot,
    News,
    NewsInstrument,
    Price,
)
from src.social.sentiment.aggregator import aggregator

logger = logging.getLogger(__name__)


class DataLoader:
    async def load_geo(self, db: AsyncSession) -> dict[str, Any]:
        from src.analysis.events import event_features

        return await event_features.load_geo(db)

    def load_geo_sync(self, db: Any) -> dict[str, Any]:
        from src.analysis.events import event_features

        return event_features.load_geo_sync(db)

    async def load_macro(self, db: AsyncSession) -> dict[str, Any]:
        return await MacroCollector.latest_values_async(db)

    def load_macro_sync(self, db: Any) -> dict[str, Any]:
        return MacroCollector.latest_values(db)

    async def load_sentiment(self, db: AsyncSession) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_SENTIMENT_DAYS)
        result = await db.execute(select(News).where(News.created_at >= cutoff))
        recent = result.scalars().all()
        news_sentiment: dict[str, Any] = {"score": 0.0, "divergence": 0.0, "source": "none", "count": 0}
        if recent:
            scores = [float(n.sentiment_weighted or n.sentiment_score or 0) for n in recent]
            mean_s = sum(scores) / len(scores)
            variance = sum((s - mean_s) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0.0
            news_sentiment = {
                "score": round(mean_s, 3),
                "divergence": round(min(variance * 2, 1.0), 3),
                "source": "rss",
                "count": len(scores),
            }

        try:
            tickers = await db.execute(select(Instrument.ticker))
            all_tickers = [r[0] for r in tickers.all() if r[0]]
            all_social = aggregator.get_all_ticker_sentiments(all_tickers)
            social_with_data = [s for s in all_social.values() if s["count"] > 0]
        except Exception:
            social_with_data = []

        if not social_with_data:
            return news_sentiment

        avg_social = sum(s["score"] for s in social_with_data) / len(social_with_data)
        total_count = sum(s["count"] for s in social_with_data)
        all_social_scores = [s["score"] for s in social_with_data]
        divergence = (max(all_social_scores) - min(all_social_scores)) / 2 if len(all_social_scores) > 1 else 0.0

        if news_sentiment["count"] > 0:
            combined = news_sentiment["score"] * 0.4 + avg_social * 0.6
            source_str = "rss+social"
        else:
            combined = avg_social
            source_str = "social"

        return {
            "score": round(combined, 3),
            "divergence": round(min(divergence, 1.0), 3),
            "source": source_str,
            "count": news_sentiment["count"] + total_count,
        }

    def load_sentiment_sync(self, db: Any, ticker: str) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_SENTIMENT_DAYS)
        recent = db.query(News).filter(News.created_at >= cutoff).all()
        news_sentiment: dict[str, Any] = {"score": 0.0, "divergence": 0.0, "source": "none", "count": 0}
        if recent:
            scores = [float(n.sentiment_weighted or n.sentiment_score or 0) for n in recent]
            mean_s = sum(scores) / len(scores)
            variance = sum((s - mean_s) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0.0
            news_sentiment = {
                "score": round(mean_s, 3),
                "divergence": round(min(variance * 2, 1.0), 3),
                "source": "rss",
                "count": len(scores),
            }

        try:
            social_entry = aggregator.get_ticker_sentiment(ticker)
        except Exception:
            social_entry = {"score": 0.0, "divergence": 0.0, "source": "social", "count": 0}

        if social_entry["count"] > 0 and news_sentiment["count"] > 0:
            combined = news_sentiment["score"] * 0.4 + social_entry["score"] * 0.6
            return {
                "score": round(combined, 3),
                "divergence": round(min(social_entry.get("divergence", 0), 1.0), 3),
                "source": "rss+social",
                "count": news_sentiment["count"] + social_entry["count"],
            }
        elif social_entry["count"] > 0:
            return {
                "score": round(social_entry["score"], 3),
                "divergence": round(min(social_entry.get("divergence", 0), 1.0), 3),
                "source": "social",
                "count": social_entry["count"],
            }
        return news_sentiment

    async def load_trends(self, db: AsyncSession, instrument_id: int) -> dict[str, Any]:
        result = {}
        for period in ("daily", "weekly", "monthly"):
            snap = (
                await db.execute(
                    select(MetricSnapshot)
                    .where(MetricSnapshot.instrument_id == instrument_id, MetricSnapshot.period == period)
                    .order_by(MetricSnapshot.taken_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if snap:
                result[period] = {
                    "price_delta": snap.delta_price_pct,
                    "score_delta": snap.delta_score,
                    "rsi_delta": snap.delta_rsi,
                    "action_changed": snap.delta_action_changed,
                    "price": snap.price,
                    "rsi": snap.rsi,
                    "signal_action": snap.signal_action,
                    "signal_score": snap.signal_score,
                }
        return result

    def load_trends_sync(self, db: Any, instrument_id: int) -> dict[str, Any]:
        result = {}
        for period in ("daily", "weekly", "monthly"):
            snap = (
                db.query(MetricSnapshot)
                .filter(MetricSnapshot.instrument_id == instrument_id, MetricSnapshot.period == period)
                .order_by(MetricSnapshot.taken_at.desc())
                .first()
            )
            if snap:
                result[period] = {
                    "price_delta": snap.delta_price_pct,
                    "score_delta": snap.delta_score,
                    "rsi_delta": snap.delta_rsi,
                    "action_changed": snap.delta_action_changed,
                    "price": snap.price,
                    "rsi": snap.rsi,
                    "signal_action": snap.signal_action,
                    "signal_score": snap.signal_score,
                }
        return result

    async def load_latest_report(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
        result = await db.execute(
            select(FinancialReport)
            .where(FinancialReport.instrument_id == instrument_id)
            .order_by(FinancialReport.report_date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "report_date": str(row.report_date),
            "period_type": row.period_type,
            "net_profit": row.net_profit,
            "revenue": row.revenue,
            "net_interest_income": row.net_interest_income,
            "operating_income": row.operating_income,
            "total_assets": row.total_assets,
            "total_liabilities": row.total_liabilities,
            "total_equity": row.total_equity,
            "loan_portfolio": row.loan_portfolio,
            "customer_deposits": row.customer_deposits,
            "cost_income_ratio": row.cost_income_ratio,
            "roe": row.roe,
            "roa": row.roa,
            "net_margin": row.net_margin,
            "npl_ratio": row.npl_ratio,
            "capital_adequacy": row.capital_adequacy,
        }

    def load_latest_report_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
        row = (
            db.query(FinancialReport)
            .filter_by(instrument_id=instrument_id)
            .order_by(FinancialReport.report_date.desc())
            .first()
        )
        if row is None:
            return None
        return {
            "report_date": str(row.report_date),
            "period_type": row.period_type,
            "net_profit": row.net_profit,
            "revenue": row.revenue,
            "net_interest_income": row.net_interest_income,
            "operating_income": row.operating_income,
            "total_assets": row.total_assets,
            "total_liabilities": row.total_liabilities,
            "total_equity": row.total_equity,
            "loan_portfolio": row.loan_portfolio,
            "customer_deposits": row.customer_deposits,
            "cost_income_ratio": row.cost_income_ratio,
            "roe": row.roe,
            "roa": row.roa,
            "net_margin": row.net_margin,
            "npl_ratio": row.npl_ratio,
            "capital_adequacy": row.capital_adequacy,
        }

    async def load_bond_offering(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
        result = await db.execute(
            select(BondOffering)
            .where(BondOffering.instrument_id == instrument_id)
            .order_by(BondOffering.offering_date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "coupon_type": row.coupon_type,
            "coupon_rate": row.coupon_rate,
            "coupon_period_days": row.coupon_period_days,
            "spread_to_key_rate": row.spread_to_key_rate,
            "yield_to_maturity": row.yield_to_maturity,
            "duration_years": row.duration_years,
            "maturity_years": row.maturity_years,
            "credit_rating": row.credit_rating,
            "has_amortization": row.has_amortization,
            "has_offer": row.has_offer,
            "min_lot_rub": row.min_lot_rub,
            "qual_investor_only": row.qual_investor_only,
            "nominal_price": row.nominal_price,
            "current_price_pct": row.current_price_pct,
        }

    def load_bond_offering_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
        row = (
            db.query(BondOffering)
            .filter_by(instrument_id=instrument_id)
            .order_by(BondOffering.offering_date.desc())
            .first()
        )
        if row is None:
            return None
        return {
            "coupon_type": row.coupon_type,
            "coupon_rate": row.coupon_rate,
            "coupon_period_days": row.coupon_period_days,
            "spread_to_key_rate": row.spread_to_key_rate,
            "yield_to_maturity": row.yield_to_maturity,
            "duration_years": row.duration_years,
            "maturity_years": row.maturity_years,
            "credit_rating": row.credit_rating,
            "has_amortization": row.has_amortization,
            "has_offer": row.has_offer,
            "min_lot_rub": row.min_lot_rub,
            "qual_investor_only": row.qual_investor_only,
            "nominal_price": row.nominal_price,
            "current_price_pct": row.current_price_pct,
        }

    async def load_fundamental_metrics(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
        result = await db.execute(
            select(FundamentalMetric)
            .where(FundamentalMetric.instrument_id == instrument_id)
            .order_by(FundamentalMetric.date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "market_cap": row.market_cap,
            "pe_ratio": row.pe_ratio,
            "pb_ratio": row.pb_ratio,
            "roe": row.roe,
            "eps": row.eps,
            "debt_equity": row.debt_equity,
        }

    def load_fundamental_metrics_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
        row = (
            db.query(FundamentalMetric)
            .filter_by(instrument_id=instrument_id)
            .order_by(FundamentalMetric.date.desc())
            .first()
        )
        if row is None:
            return None
        return {
            "market_cap": row.market_cap,
            "pe_ratio": row.pe_ratio,
            "pb_ratio": row.pb_ratio,
            "roe": row.roe,
            "eps": row.eps,
            "debt_equity": row.debt_equity,
        }

    @staticmethod
    def augment_with_sector_avg(
        db: Any, fund_metrics: dict[str, Any] | None, inst: Instrument
    ) -> dict[str, Any] | None:
        if not fund_metrics:
            return fund_metrics
        sector = inst.sector
        if not sector:
            return fund_metrics

        avg_pe = (
            db.query(func.avg(FundamentalMetric.pe_ratio))
            .join(Instrument, Instrument.id == FundamentalMetric.instrument_id)
            .filter(Instrument.sector == sector, FundamentalMetric.pe_ratio.isnot(None), FundamentalMetric.pe_ratio > 0)
            .scalar()
        )
        if avg_pe is not None:
            fund_metrics["sector_avg_pe"] = round(float(avg_pe), 2)
        avg_pb = (
            db.query(func.avg(FundamentalMetric.pb_ratio))
            .join(Instrument, Instrument.id == FundamentalMetric.instrument_id)
            .filter(Instrument.sector == sector, FundamentalMetric.pb_ratio.isnot(None), FundamentalMetric.pb_ratio > 0)
            .scalar()
        )
        if avg_pb is not None:
            fund_metrics["sector_avg_pb"] = round(float(avg_pb), 2)
        return fund_metrics


data_loader = DataLoader()
