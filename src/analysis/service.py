import logging
from collections.abc import Sequence
from datetime import date
from typing import Any, Literal, cast

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.fundamental import FundamentalAnalyzer
from src.analysis.ml.price_targets import build_trade_plan
from src.analysis.ml.price_targets import to_dict as trade_plan_to_dict
from src.analysis.multi_timeframe import MultiTimeframeAnalyzer
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.volatility import VolatilityRegimeDetector
from src.constants import NEWS_SENTIMENT_DAYS
from src.db.models import (
    BondOffering,
    Dividend,
    FinancialReport,
    FundamentalMetric,
    GeoRiskScore,
    Indicator,
    Instrument,
    MarketEvent,
    News,
    NewsInstrument,
    Price,
    Signal,
)
from src.llm.router import llm
from src.signal.engine import SignalFusionEngine, compute_risk_metrics

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self) -> None:
        self.analyzer = TechnicalAnalyzer()
        self.fundamental = FundamentalAnalyzer()
        self.fusion = SignalFusionEngine()
        self._prophet_cache: dict[str, Any] = {}
        self._ensemble_cache: dict[str, Any] = {}
        self.volatility = VolatilityRegimeDetector()
        self.mtf = MultiTimeframeAnalyzer()

    def _get_prophet(self, ticker: str = "") -> Any:
        if ticker not in self._prophet_cache:
            from src.analysis.ml.prophet_model import ProphetPredictor

            self._prophet_cache[ticker] = ProphetPredictor(ticker=ticker)
        return self._prophet_cache[ticker]

    def _get_ensemble(self, ticker: str = "") -> Any:
        if ticker not in self._ensemble_cache:
            from src.analysis.ml.ensemble import EnsemblePredictor

            self._ensemble_cache[ticker] = EnsemblePredictor(ticker=ticker)
        return self._ensemble_cache[ticker]

    def _price_df(self, prices: Sequence[Price]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"date": p.date, "open": p.open, "high": p.high, "low": p.low, "close": p.close, "volume": p.volume}
                for p in prices
            ]
        )

    def _indicator_df(self, rows: Sequence[Indicator]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": r.date,
                    "rsi": r.rsi,
                    "macd_line": r.macd_line,
                    "macd_signal": r.macd_signal,
                    "macd_hist": r.macd_hist,
                    "sma_20": r.sma_20,
                    "sma_50": r.sma_50,
                    "sma_200": r.sma_200,
                    "bb_upper": r.bb_upper,
                    "bb_lower": r.bb_lower,
                    "bb_mid": r.bb_mid,
                    "volume_sma_20": r.volume_sma_20,
                    "atr": r.atr,
                }
                for r in rows
            ]
        )

    def _dividend_df(self, divs: Sequence[Dividend]) -> pd.DataFrame:
        return pd.DataFrame([{"date": d.date, "amount": d.amount} for d in divs])

    def _build_event_features(self, events: list[MarketEvent], dates: pd.Series) -> pd.DataFrame:
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

    def _compute_ml(
        self,
        df: pd.DataFrame,
        ind_df: pd.DataFrame,
        ticker: str = "",
        events: list[MarketEvent] | None = None,
    ) -> dict[str, Any] | None:
        if len(df) < 60:
            return None
        try:
            anomaly_mask = None
            if events:
                ef = self._build_event_features(events, ind_df["date"])
                ind_df = ind_df.merge(ef, on="date", how="left")
                for c in ["event_count_30d", "event_severity_30d", "sanctions_30d", "days_since_major_event"]:
                    if c in ind_df.columns:
                        ind_df[c] = ind_df[c].fillna(0)
                if "is_anomaly" in ind_df.columns:
                    anomaly_mask = ind_df["is_anomaly"].fillna(False).to_numpy(dtype=bool)
                    ind_df = ind_df.drop(columns=["is_anomaly"])

            pr = self._get_prophet(ticker).predict(df)
            ensemble = self._get_ensemble(ticker).predict(ind_df, anomaly_mask=anomaly_mask)
            ml = pr
            ml["ml_confidence"] = max(pr.get("confidence", 0), ensemble.get("confidence", 0))
            ml["xgb_action"] = ensemble.get("xgb_action", "NEUTRAL")
            ml["ensemble"] = {
                "lgb_action": ensemble.get("lgb_action", "NEUTRAL"),
                "cat_action": ensemble.get("cat_action", "NEUTRAL"),
                "model_votes": ensemble.get("model_votes", {}),
            }
            return cast(dict[str, Any], ml)
        except Exception:
            logger.warning("ML prediction failed", exc_info=True)
            return None

    async def _load_geo(self, db: AsyncSession) -> dict[str, Any]:
        score = await self._compute_geo_from_events(db)
        if score is not None:
            return {"score": score}
        result = await db.execute(select(GeoRiskScore).order_by(GeoRiskScore.date.desc()).limit(1))
        geo = result.scalar_one_or_none()
        return {"score": geo.score} if geo else {"score": 0.0}

    async def _compute_geo_from_events(self, db: AsyncSession) -> float | None:
        from datetime import datetime, timedelta, timezone

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

    async def _load_macro(self, db: AsyncSession) -> dict[str, Any]:
        from src.collectors.macro import MacroCollector

        return await MacroCollector.latest_values_async(db)

    async def _load_all_events(self, db: AsyncSession) -> list[MarketEvent]:
        result = await db.execute(select(MarketEvent).order_by(MarketEvent.date))
        return list(result.scalars().all())

    def _load_all_events_sync(self, db: Any) -> list[MarketEvent]:
        return list(db.query(MarketEvent).order_by(MarketEvent.date).all())

    async def _load_market_events(self, db: AsyncSession, days: int = 30) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

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

        from datetime import datetime, timedelta, timezone

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

    def _compute_geo_from_events_sync(self, db: Any) -> float | None:
        from datetime import datetime, timedelta, timezone

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

    def _load_market_events_sync(self, db: Any, days: int = 30) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

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

    async def _load_sentiment(self, db: AsyncSession) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

        from src.db.models import News

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
            from src.social.sentiment.aggregator import aggregator

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

    async def _load_trends(self, db: AsyncSession, instrument_id: int) -> dict[str, Any]:
        from src.db.models import MetricSnapshot

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

    async def _load_latest_report(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
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

    def _load_latest_report_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
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

    async def _load_bond_offering(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
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

    def _load_bond_offering_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
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

    def _load_sentiment_sync(self, db: Any, ticker: str) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

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
            from src.social.sentiment.aggregator import aggregator

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

    def _build_trade_plan(
        self, df: pd.DataFrame, ind_df: pd.DataFrame, tech_signal: dict[str, Any]
    ) -> dict[str, Any] | None:
        if df.empty or len(df) < 20 or ind_df.empty:
            return None
        latest = df.iloc[-1]
        ind_latest = ind_df.iloc[-1]
        close = float(latest["close"])
        sma20 = float(ind_latest.get("sma_20") or close)
        atr = float(ind_latest.get("atr") or close * 0.02)
        if atr <= 0 or close <= 0:
            return None
        side: Literal["buy", "sell"] = "buy"
        if tech_signal.get("action") == "SELL":
            side = "sell"
        plan = build_trade_plan(close, sma20, atr, df, side=side)
        return trade_plan_to_dict(plan)

    def _analyze_core(
        self,
        df: pd.DataFrame,
        ind_df: pd.DataFrame,
        inst: Instrument,
        ticker: str,
        fund_metrics: dict[str, Any] | None,
        divs: Sequence[Dividend],
        geo_score: float,
        macro_context: dict[str, Any],
        sentiment: dict[str, Any],
        event_context: dict[str, Any],
        market_events: list[MarketEvent],
        trends: dict[str, Any],
        financial_report: dict[str, Any] | None = None,
        bond_offering: dict[str, Any] | None = None,
        with_ml: bool = True,
    ) -> dict[str, Any]:
        tech_signal = self.analyzer.generate_signal(ind_df)
        div_df = self._dividend_df(divs)
        fund = self.fundamental.analyze(df, div_df, metrics=fund_metrics)
        ml = self._compute_ml(df, ind_df, ticker=ticker, events=market_events) if with_ml else None
        geo = {"score": geo_score}
        volatility_regime = self.volatility.detect(df, ind_df)
        risk_metrics = compute_risk_metrics(df["close"].tolist())
        mtf_data = self.mtf.compute_all(df)
        mtf_concordance = self.mtf.concordance(mtf_data) if mtf_data else None
        trade_plan = self._build_trade_plan(df, ind_df, tech_signal) if not ind_df.empty else None
        fused = self.fusion.fuse(
            ticker=ticker.upper(),
            instrument_type=str(inst.instrument_type or "stock"),
            technical=tech_signal,
            fundamental=fund,
            geo=geo,
            ml_prediction=ml,
            volatility_regime=volatility_regime,
            risk_metrics=risk_metrics,
            macro_context=macro_context,
            sentiment=sentiment,
            mtf=mtf_concordance,
            event_context=event_context,
            trade_plan=trade_plan,
        )
        fused["trends"] = trends
        fused["recent_events"] = event_context.get("recent_for_llm", [])
        if financial_report:
            fused["financial_report"] = financial_report
            fused["financial_facts"] = self.fundamental.analyze_report(financial_report)
        if bond_offering:
            fused["bond_offering"] = bond_offering
        return fused

    async def analyze_single(
        self, db: AsyncSession, inst: Instrument, ticker: str, with_ml: bool = True
    ) -> dict[str, Any]:
        price_result = await db.execute(select(Price).where(Price.instrument_id == inst.id).order_by(Price.date))
        prices = price_result.scalars().all()
        if len(prices) < 50:
            raise ValueError(f"Not enough price data for {ticker}")
        df = self._price_df(prices)

        ind_result = await db.execute(
            select(Indicator).where(Indicator.instrument_id == inst.id).order_by(Indicator.date)
        )
        ind_rows = ind_result.scalars().all()
        if len(ind_rows) < 2:
            raise ValueError(f"Not enough indicator data for {ticker}")
        ind_df = self._indicator_df(ind_rows)
        ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

        div_result = await db.execute(select(Dividend).where(Dividend.instrument_id == inst.id))
        divs = div_result.scalars().all()

        fund_metrics = await self._load_fundamental_metrics(db, int(inst.id))
        if fund_metrics and inst.sector:
            avg_pe = (
                await db.execute(
                    select(func.avg(FundamentalMetric.pe_ratio))
                    .join(Instrument, Instrument.id == FundamentalMetric.instrument_id)
                    .where(
                        Instrument.sector == inst.sector,
                        FundamentalMetric.pe_ratio.isnot(None),
                        FundamentalMetric.pe_ratio > 0,
                    )
                )
            ).scalar()
            if avg_pe is not None:
                fund_metrics["sector_avg_pe"] = round(float(avg_pe), 2)
            avg_pb = (
                await db.execute(
                    select(func.avg(FundamentalMetric.pb_ratio))
                    .join(Instrument, Instrument.id == FundamentalMetric.instrument_id)
                    .where(
                        Instrument.sector == inst.sector,
                        FundamentalMetric.pb_ratio.isnot(None),
                        FundamentalMetric.pb_ratio > 0,
                    )
                )
            ).scalar()
            if avg_pb is not None:
                fund_metrics["sector_avg_pb"] = round(float(avg_pb), 2)
        geo_score = (await self._load_geo(db)).get("score", 0.0)
        macro_context = await self._load_macro(db)
        sentiment = await self._load_sentiment(db)
        event_context = await self._load_market_events(db)
        market_events = await self._load_all_events(db)
        trends = await self._load_trends(db, int(inst.id))
        financial_report = await self._load_latest_report(db, int(inst.id))
        bond_offering = await self._load_bond_offering(db, int(inst.id))

        return self._analyze_core(
            df=df,
            ind_df=ind_df,
            inst=inst,
            ticker=ticker,
            fund_metrics=fund_metrics,
            divs=divs,
            geo_score=geo_score,
            macro_context=macro_context,
            sentiment=sentiment,
            event_context=event_context,
            market_events=market_events,
            trends=trends,
            financial_report=financial_report,
            bond_offering=bond_offering,
            with_ml=with_ml,
        )

    async def analyze_all(
        self, db: AsyncSession, updated_ids: set[int] | None = None, with_ml: bool = True
    ) -> list[dict[str, Any]]:
        q = select(Instrument)
        if updated_ids is not None:
            q = q.where(Instrument.id.in_(updated_ids))
        result = await db.execute(q)
        instruments = result.scalars().all()

        signals: list[dict[str, Any]] = []
        for inst in instruments:
            cached_result = await db.execute(
                select(Signal).where(
                    Signal.instrument_id == inst.id,
                    func.date(Signal.date) == date.today(),
                )
            )
            cached = cached_result.scalar_one_or_none()
            if cached and cached.fused_json:
                fused_json = cached.fused_json
                if isinstance(fused_json, dict):
                    signals.append(fused_json)
                continue

            try:
                fused = await self.analyze_single(db, inst, str(inst.ticker), with_ml=with_ml)
                await self.fusion.save_signal(db, int(inst.id), fused)
                signals.append(fused)
            except ValueError:
                continue
        return signals

    async def analyze_with_advice(
        self, db: AsyncSession, inst: Instrument, ticker: str, with_ml: bool = True
    ) -> tuple[dict[str, Any], str]:
        fused = await self.analyze_single(db, inst, ticker, with_ml=with_ml)
        advice = await llm.advise(fused)
        return fused, advice

    def _load_trends_sync(self, db: Any, instrument_id: int) -> dict[str, Any]:
        from src.db.models import MetricSnapshot

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

    def _analyze_single_sync(self, db: Any, inst: Any, ticker: str, with_ml: bool = True) -> dict[str, Any]:
        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices) < 50:
            raise ValueError(f"Not enough price data for {ticker}")
        df = self._price_df(prices)

        ind_rows = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date).all()
        if len(ind_rows) < 2:
            raise ValueError(f"Not enough indicator data for {ticker}")
        ind_df = self._indicator_df(ind_rows)
        ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

        divs = db.query(Dividend).filter_by(instrument_id=inst.id).all()
        fund_metrics = self._load_fundamental_metrics_sync(db, inst.id)
        fund_metrics = self._augment_with_sector_avg(db, fund_metrics, inst)

        geo_val = self._compute_geo_from_events_sync(db)
        if geo_val is None:
            geo_row = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
            geo_val = geo_row.score if geo_row else 0.0

        from src.collectors.macro import MacroCollector

        macro_context = MacroCollector.latest_values(db)
        sentiment = self._load_sentiment_sync(db, ticker)
        market_events = self._load_all_events_sync(db)
        event_context = self._load_market_events_sync(db)
        trends = self._load_trends_sync(db, inst.id)
        financial_report = self._load_latest_report_sync(db, inst.id)
        bond_offering = self._load_bond_offering_sync(db, inst.id)

        return self._analyze_core(
            df=df,
            ind_df=ind_df,
            inst=inst,
            ticker=ticker,
            fund_metrics=fund_metrics,
            divs=divs,
            geo_score=geo_val,
            macro_context=macro_context,
            sentiment=sentiment,
            event_context=event_context,
            market_events=market_events,
            trends=trends,
            financial_report=financial_report,
            bond_offering=bond_offering,
            with_ml=with_ml,
        )

    async def _load_fundamental_metrics(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
        from src.db.models import FundamentalMetric

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

    def _load_fundamental_metrics_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
        from src.db.models import FundamentalMetric

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
    def _augment_with_sector_avg(
        db: Any, fund_metrics: dict[str, Any] | None, inst: Instrument
    ) -> dict[str, Any] | None:
        if not fund_metrics:
            return fund_metrics
        sector = inst.sector
        if not sector:
            return fund_metrics
        from src.db.models import FundamentalMetric

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

    def analyze_all_sync(
        self, db: Any, updated_ids: set[int] | None = None, with_ml: bool = True
    ) -> list[dict[str, Any]]:
        instruments = db.query(Instrument)
        if updated_ids is not None:
            instruments = instruments.filter(Instrument.id.in_(updated_ids))
        instruments = instruments.all()

        signals: list[dict[str, Any]] = []
        for inst in instruments:
            cached = (
                db.query(Signal)
                .filter(
                    Signal.instrument_id == inst.id,
                    func.date(Signal.date) == date.today(),
                )
                .first()
            )
            if cached and cached.fused_json:
                fused_json = cached.fused_json
                if isinstance(fused_json, dict):
                    signals.append(fused_json)
                continue

            try:
                fused = self._analyze_single_sync(db, inst, str(inst.ticker), with_ml=with_ml)
                self.fusion.save_signal_sync(db, inst.id, fused)
                signals.append(fused)
            except (ValueError, Exception) as e:
                logger.warning("analyze_all_sync failed for %s: %s", inst.ticker, e)
                continue
        return signals

    def load_ticker_context(self, db: Any, ticker: str) -> str:
        """Build a human-readable string of all available data for a ticker.

        Used by LLM question answering to provide rich context.
        """
        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            return ""

        lines = []
        itype = str(inst.instrument_type or "stock")

        lines.append(f"Название: {inst.full_name or '—'}")
        lines.append(f"Сектор: {inst.sector or '—'}")
        lines.append(f"Тип: {itype}")
        lines.append(f"Лот: {inst.lot_size or 1} шт")
        lines.append("")

        # ── Price stats ──────────────────────────────────────────────
        prices_q = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices_q) >= 20:
            closes = [p.close for p in prices_q if p.close]
            if closes:
                last = closes[-1]
                lines.append(f"Текущая цена: {last:.2f} ₽")

                def _add_stats(c: list[float], label: str) -> None:
                    if len(c) < 2:
                        return
                    mn, mx = min(c), max(c)
                    avg = sum(c) / len(c)
                    chg = (c[-1] - c[0]) / c[0] * 100
                    lines.append(f"Цена {label}: мин {mn:.2f}, макс {mx:.2f}, ср {avg:.2f}, изм {chg:+.2f}%")

                _add_stats(closes, "за всё время")
                for period, days in [("1 год", 252), ("6 мес", 126), ("3 мес", 63), ("1 мес", 21), ("1 нед", 7)]:
                    if len(closes) >= days:
                        _add_stats(closes[-days:], f"за {period}")

                # ── Technical indicators ──────────────────────────────
                ind = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date.desc()).first()
                if ind:
                    lines.append("")
                    if ind.rsi is not None:
                        rsi_label = "перегрет" if ind.rsi > 70 else ("перепродан" if ind.rsi < 30 else "нейтрален")
                        lines.append(f"RSI: {ind.rsi:.1f} ({rsi_label})")
                    if ind.sma_20 is not None:
                        lines.append(f"SMA20: {ind.sma_20:.2f} (цена {'выше' if last > ind.sma_20 else 'ниже'})")
                    if ind.sma_50 is not None:
                        lines.append(f"SMA50: {ind.sma_50:.2f} (цена {'выше' if last > ind.sma_50 else 'ниже'})")
                    if ind.sma_200 is not None:
                        lines.append(f"SMA200: {ind.sma_200:.2f} (цена {'выше' if last > ind.sma_200 else 'ниже'})")
                    if ind.bb_upper is not None and ind.bb_lower is not None:
                        bb_pos = (
                            "у верхней"
                            if last >= ind.bb_upper
                            else ("у нижней" if last <= ind.bb_lower else "в середине")
                        )
                        lines.append(f"Боллинджер: {bb_pos} ({ind.bb_lower:.1f}–{ind.bb_upper:.1f})")
                    if ind.macd_hist is not None:
                        lines.append(f"MACD: {ind.macd_hist:.2f} ({'бычья' if ind.macd_hist > 0 else 'медвежья'})")
                    if ind.atr is not None:
                        lines.append(f"ATR: {ind.atr:.2f}")
                    if ind.volume_sma_20 is not None and prices_q and prices_q[-1].volume:
                        vol_ratio = prices_q[-1].volume / ind.volume_sma_20 if ind.volume_sma_20 > 0 else 1
                        vol_label = "выше" if vol_ratio > 1.2 else ("ниже" if vol_ratio < 0.8 else "около")
                        lines.append(f"Объём: {vol_label} среднего ({vol_ratio:.1f}x)")
            else:
                last = None
        else:
            last = None

        # ── Financial report ─────────────────────────────────────────
        fin = self._load_latest_report_sync(db, inst.id)
        if fin:
            facts = self.fundamental.analyze_report(fin)
            if facts:
                lines.append("")
                lines.append("Финансовая отчётность:")
                for f in facts:
                    lines.append(f"  {f}")

        # ── Bond offering ────────────────────────────────────────────
        if itype == "bond":
            bo = self._load_bond_offering_sync(db, inst.id)
            if bo:
                lines.append("")
                lines.append("Параметры выпуска:")
                for k, v in bo.items():
                    if v is not None:
                        lines.append(f"  {k}: {v}")

        # ── Dividends (stocks only) ──────────────────────────────────
        divs = db.query(Dividend).filter_by(instrument_id=inst.id).order_by(Dividend.date.desc()).limit(5).all()
        if divs and last and last > 0:
            lines.append("")
            lines.append("Дивиденды (последние):")
            for d in divs:
                yield_pct = d.amount / last * 100
                lines.append(f"  {d.date}: {d.amount:.4f} ₽/акцию (дох-ть {yield_pct:.2f}%)")

        # ── News (last 30 days) ──────────────────────────────────────
        from datetime import datetime, timedelta, timezone

        # Check if news is stale and refresh on demand
        latest_news = (
            db.query(News)
            .join(NewsInstrument, News.id == NewsInstrument.news_id)
            .filter(NewsInstrument.instrument_id == inst.id)
            .order_by(News.created_at.desc())
            .limit(1)
            .first()
        )
        if latest_news:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            created = latest_news.created_at.replace(tzinfo=None) if latest_news.created_at else now
            age_hours = (now - created).total_seconds() / 3600
        else:
            age_hours = float("inf")

        from src.constants import NEWS_STALE_HOURS

        if age_hours > NEWS_STALE_HOURS:
            from src.collectors.news import NewsCollector

            NewsCollector.collect_for_ticker_sync(db, ticker)

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        recent_news = (
            db.query(News)
            .join(NewsInstrument, News.id == NewsInstrument.news_id)
            .filter(NewsInstrument.instrument_id == inst.id, News.created_at >= cutoff)
            .order_by(News.created_at.desc())
            .limit(10)
            .all()
        )
        if recent_news:
            scores = [n.sentiment_weighted or n.sentiment_score or 0 for n in recent_news]
            avg_sent = sum(scores) / len(scores)
            pos = sum(1 for s in scores if s > 0)
            neg = sum(1 for s in scores if s < 0)
            lines.append("")
            lines.append(f"Новости (30д): {len(recent_news)} шт, сентимент {avg_sent:+.2f} (+{pos}/–{neg})")
            for n in recent_news[:5]:
                s = n.sentiment_weighted or n.sentiment_score or 0
                icon = "🟢" if s > 0 else ("🔴" if s < 0 else "⚪")
                lines.append(f"  {icon} {n.title[:150]}")

        # ── Fused signal ─────────────────────────────────────────────
        try:
            fused = self._analyze_single_sync(db, inst, ticker.upper(), with_ml=True)
            if fused:
                lines.append("")
                lines.append(f"Сигнал: {fused['action']} (уверенность {fused['confidence']:.0%})")
                ml = fused.get("components", {}).get("ml", {})
                if ml and ml.get("change_pct") is not None:
                    lines.append(f"ML прогноз: {ml['change_pct']:+.2f}% (цель {ml.get('target_price', 0):.0f} ₽)")
                rr = fused.get("reasons", [])
                if rr:
                    lines.append("Обоснование:")
                    for r in rr[:5]:
                        lines.append(f"  • {r}")
        except Exception:
            pass

        return "\n".join(lines)

    def train_models(self, db: Any, ticker: str | None = None) -> dict[str, bool]:
        q = select(Instrument)
        if ticker:
            q = q.where(Instrument.ticker == ticker.upper())
        result = db.execute(q)
        instruments = result.scalars().all()

        all_results: dict[str, bool] = {}
        for inst in instruments:
            sym = str(inst.ticker or "")
            prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
            if len(prices) < 60:
                logger.info("Skipping %s: only %d prices", sym, len(prices))
                continue
            df = self._price_df(prices)

            ind_rows = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date).all()
            if len(ind_rows) < 2:
                logger.info("Skipping %s: no indicators", sym)
                continue
            ind_df = self._indicator_df(ind_rows)
            ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

            all_events = self._load_all_events_sync(db)
            anomaly_mask = None
            train_df = ind_df.copy()
            if all_events:
                ef = self._build_event_features(all_events, ind_df["date"])
                train_df = ind_df.merge(ef, on="date", how="left")
                for c in ["event_count_30d", "event_severity_30d", "sanctions_30d", "days_since_major_event"]:
                    if c in train_df.columns:
                        train_df[c] = train_df[c].fillna(0)
                if "is_anomaly" in train_df.columns:
                    anomaly_mask = train_df["is_anomaly"].fillna(False).to_numpy(dtype=bool)
                    train_df = train_df.drop(columns=["is_anomaly"])

            ensemble = self._get_ensemble(sym)
            ensemble_ok = ensemble.train_all(train_df, anomaly_mask=anomaly_mask)

            prophet = self._get_prophet(sym)
            prophet_ok = prophet.train(df)

            all_results[sym] = all(ensemble_ok.values()) and prophet_ok
            logger.info(
                "Model training for %s: ensemble=%s prophet=%s",
                sym,
                "OK" if all(ensemble_ok.values()) else "partial",
                "OK" if prophet_ok else "FAIL",
            )
        return all_results


analysis_service = AnalysisService()
