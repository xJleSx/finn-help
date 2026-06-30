from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any, Literal, cast

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.events import EventFeatureBuilder, event_features
from src.analysis.fundamental import FundamentalAnalyzer
from src.analysis.loader import DataLoader, data_loader
from src.analysis.ml.price_targets import build_trade_plan
from src.analysis.ml.price_targets import to_dict as trade_plan_to_dict
from src.analysis.ml_coordinator import MLCoordinator, ml_coordinator
from src.analysis.multi_timeframe import MultiTimeframeAnalyzer
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.volatility import VolatilityRegimeDetector
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
        self.volatility = VolatilityRegimeDetector()
        self.mtf = MultiTimeframeAnalyzer()
        self.loader: DataLoader = data_loader
        self.ml: MLCoordinator = ml_coordinator
        self.events: EventFeatureBuilder = event_features

    # ── Backward-compat proxies ──────────────────────────────────────

    def _price_df(self, prices: Sequence[Price]) -> pd.DataFrame:
        return self.ml.price_df(list(prices))

    def _indicator_df(self, rows: Sequence[Indicator]) -> pd.DataFrame:
        return self.ml.indicator_df(list(rows))

    def _dividend_df(self, divs: Sequence[Dividend]) -> pd.DataFrame:
        return self.ml.dividend_df(list(divs))

    def _get_prophet(self, ticker: str = "") -> Any:
        return self.ml.get_prophet(ticker)

    def _get_ensemble(self, ticker: str = "") -> Any:
        return self.ml.get_ensemble(ticker)

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
                ef = self.events.build_features(events, ind_df["date"])
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
        return await self.loader.load_geo(db)

    def _compute_geo_from_events_sync(self, db: Any) -> float | None:
        return self.events.compute_geo_from_events_sync(db)

    async def _load_macro(self, db: AsyncSession) -> dict[str, Any]:
        return await self.loader.load_macro(db)

    async def _load_all_events(self, db: AsyncSession) -> list[MarketEvent]:
        return await self.events.load_all_events(db)

    def _load_all_events_sync(self, db: Any) -> list[MarketEvent]:
        return self.events.load_all_events_sync(db)

    async def _load_market_events(self, db: AsyncSession, days: int = 30) -> dict[str, Any]:
        return await self.events.load_market_events(db, days=days)

    def _load_market_events_sync(self, db: Any, days: int = 30) -> dict[str, Any]:
        return self.events.load_market_events_sync(db, days=days)

    async def _load_sentiment(self, db: AsyncSession) -> dict[str, Any]:
        return await self.loader.load_sentiment(db)

    def _load_sentiment_sync(self, db: Any, ticker: str) -> dict[str, Any]:
        return self.loader.load_sentiment_sync(db, ticker)

    async def _load_trends(self, db: AsyncSession, instrument_id: int) -> dict[str, Any]:
        return await self.loader.load_trends(db, instrument_id)

    def _load_trends_sync(self, db: Any, instrument_id: int) -> dict[str, Any]:
        return self.loader.load_trends_sync(db, instrument_id)

    async def _load_latest_report(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
        return await self.loader.load_latest_report(db, instrument_id)

    def _load_latest_report_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
        return self.loader.load_latest_report_sync(db, instrument_id)

    async def _load_bond_offering(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
        return await self.loader.load_bond_offering(db, instrument_id)

    def _load_bond_offering_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
        return self.loader.load_bond_offering_sync(db, instrument_id)

    async def _load_fundamental_metrics(self, db: AsyncSession, instrument_id: int) -> dict[str, Any] | None:
        return await self.loader.load_fundamental_metrics(db, instrument_id)

    def _load_fundamental_metrics_sync(self, db: Any, instrument_id: int) -> dict[str, Any] | None:
        return self.loader.load_fundamental_metrics_sync(db, instrument_id)

    @staticmethod
    def _augment_with_sector_avg(
        db: Any, fund_metrics: dict[str, Any] | None, inst: Instrument
    ) -> dict[str, Any] | None:
        return DataLoader.augment_with_sector_avg(db, fund_metrics, inst)

    # ── Core orchestration ───────────────────────────────────────────

    def _build_event_features(self, events: list[MarketEvent], dates: pd.Series) -> pd.DataFrame:
        return self.events.build_features(events, dates)

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

        fund_metrics = await self.loader.load_fundamental_metrics(db, int(inst.id))
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

        geo_score = (await self.loader.load_geo(db)).get("score", 0.0)
        macro_context = await self.loader.load_macro(db)
        sentiment = await self.loader.load_sentiment(db)
        event_context = await self.events.load_market_events(db)
        market_events = await self.events.load_all_events(db)
        trends = await self.loader.load_trends(db, int(inst.id))
        financial_report = await self.loader.load_latest_report(db, int(inst.id))
        bond_offering = await self.loader.load_bond_offering(db, int(inst.id))

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
        fund_metrics = self.loader.load_fundamental_metrics_sync(db, inst.id)
        fund_metrics = self.loader.augment_with_sector_avg(db, fund_metrics, inst)

        geo_val = self.events.compute_geo_from_events_sync(db)
        if geo_val is None:
            geo_row = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
            geo_val = geo_row.score if geo_row else 0.0

        from src.collectors.macro import MacroCollector

        macro_context = MacroCollector.latest_values(db)
        sentiment = self.loader.load_sentiment_sync(db, ticker)
        market_events = self.events.load_all_events_sync(db)
        event_context = self.events.load_market_events_sync(db)
        trends = self.loader.load_trends_sync(db, inst.id)
        financial_report = self.loader.load_latest_report_sync(db, inst.id)
        bond_offering = self.loader.load_bond_offering_sync(db, inst.id)

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

    # ── Ticker context & training ─────────────────────────────────────

    def load_ticker_context(self, db: Any, ticker: str) -> str:
        from src.analysis.context import ticker_context_builder

        return ticker_context_builder.build(db, ticker)

    def train_models(self, db: Any, ticker: str | None = None) -> dict[str, bool]:
        from sqlalchemy import select as sa_select

        q = sa_select(Instrument)
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

            all_events = self.events.load_all_events_sync(db)
            anomaly_mask = None
            train_df = ind_df.copy()
            if all_events:
                ef = self.events.build_features(all_events, ind_df["date"])
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
