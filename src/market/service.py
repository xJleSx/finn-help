from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.ml.price_targets import build_trade_plan
from src.analysis.ml.price_targets import to_dict as trade_plan_to_dict
from src.analysis.service import AnalysisService
from src.db.models import GeoRiskScore, Indicator, Instrument, News, Price, Signal
from src.llm.router import LLMRouter
from src.notifications.service import NotificationService

logger = structlog.get_logger(__name__)


class MarketService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._analysis = AnalysisService()
        self._llm = LLMRouter()
        self._notifications = NotificationService(db=self.db)

    async def list_instruments(self, type_filter: Optional[str] = None) -> list[dict[str, Any]]:
        q = select(Instrument)
        if type_filter:
            q = q.where(Instrument.instrument_type == type_filter)
        q = q.order_by(Instrument.ticker)
        result = await self.db.execute(q)
        instruments = result.scalars().all()

        output = []
        for inst in instruments:
            price_result = await self.db.execute(
                select(Price).where(Price.instrument_id == inst.id).order_by(Price.date.desc()).limit(1)
            )
            last_price = price_result.scalar_one_or_none()
            output.append(
                {
                    "id": inst.id,
                    "ticker": inst.ticker,
                    "full_name": inst.full_name,
                    "sector": inst.sector,
                    "type": inst.instrument_type,
                    "last_price": last_price.close if last_price else None,
                    "last_date": last_price.date.isoformat() if last_price else None,
                }
            )
        return output

    async def get_instrument(self, ticker: str) -> dict[str, Any]:
        result = await self.db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(404, "Instrument not found")
        return {
            "id": inst.id,
            "ticker": inst.ticker,
            "full_name": inst.full_name,
            "isin": inst.isin,
            "sector": inst.sector,
            "type": inst.instrument_type,
            "lot_size": inst.lot_size,
            "currency": inst.currency,
        }

    async def get_prices(self, ticker: str, days: int = 365) -> list[dict[str, Any]]:
        result = await self.db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(404, "Instrument not found")

        cutoff = date.today() - timedelta(days=days)
        price_result = await self.db.execute(
            select(Price).where(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date)
        )
        prices = price_result.scalars().all()
        return [
            {
                "date": p.date.isoformat(),
                "open": p.open,
                "high": p.high,
                "low": p.low,
                "close": p.close,
                "volume": p.volume,
            }
            for p in prices
        ]

    async def get_indicators(self, ticker: str, days: int = 90) -> list[dict[str, Any]]:
        result = await self.db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(404, "Instrument not found")

        cutoff = date.today() - timedelta(days=days)
        ind_result = await self.db.execute(
            select(Indicator).where(Indicator.instrument_id == inst.id, Indicator.date >= cutoff).order_by(Indicator.date)
        )
        inds = ind_result.scalars().all()
        return [
            {
                "date": i.date.isoformat(),
                "rsi": i.rsi,
                "macd_line": i.macd_line,
                "macd_signal": i.macd_signal,
                "macd_hist": i.macd_hist,
                "sma_20": i.sma_20,
                "sma_50": i.sma_50,
                "sma_200": i.sma_200,
                "bb_upper": i.bb_upper,
                "bb_lower": i.bb_lower,
                "bb_mid": i.bb_mid,
                "volume_sma_20": i.volume_sma_20,
                "atr": i.atr,
            }
            for i in inds
        ]

    async def _resolve_signal(self, ticker: str) -> tuple[Instrument, Any]:
        result = await self.db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(404, "Instrument not found")

        signal_result = await self.db.execute(
            select(Signal)
            .where(
                Signal.instrument_id == inst.id,
                func.date(Signal.date) == date.today(),
            )
            .order_by(Signal.date.desc())
            .limit(1)
        )
        cached = signal_result.scalar_one_or_none()
        if cached and cached.fused_json:
            return inst, cached.fused_json

        try:
            fused = await self._analysis.analyze_single(self.db, inst, ticker)
        except ValueError as e:
            raise HTTPException(400, str(e))

        await self._analysis.fusion.save_signal(self.db, int(inst.id), fused)
        return inst, fused

    async def get_signal(self, ticker: str) -> Any:
        _, fused = await self._resolve_signal(ticker)
        return fused

    async def get_trade_plan(self, ticker: str, profile: str = "balanced") -> dict[str, Any]:
        result = await self.db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(404, "Instrument not found")

        price_result = await self.db.execute(select(Price).where(Price.instrument_id == inst.id).order_by(Price.date))
        prices = price_result.scalars().all()
        if len(prices) < 20:
            raise HTTPException(400, "Not enough price data")

        df = pd.DataFrame(
            [
                {"date": p.date, "open": p.open, "high": p.high, "low": p.low, "close": p.close, "volume": p.volume}
                for p in prices
            ]
        )
        ind_result = await self.db.execute(select(Indicator).where(Indicator.instrument_id == inst.id).order_by(Indicator.date))
        inds = ind_result.scalars().all()
        ind_df = pd.DataFrame(
            [
                {
                    "date": i.date,
                    "rsi": i.rsi,
                    "atr": i.atr,
                    "sma_20": i.sma_20,
                    "sma_50": i.sma_50,
                    "macd_hist": i.macd_hist,
                }
                for i in inds
            ]
        )

        if ind_df.empty:
            raise HTTPException(400, "No indicator data")

        latest = df.iloc[-1]
        ind_latest = ind_df.iloc[-1]
        close = float(latest["close"])
        sma20 = float(ind_latest.get("sma_20") or close)
        atr = float(ind_latest.get("atr") or close * 0.02)
        if atr <= 0 or close <= 0:
            raise HTTPException(400, "Invalid price data")

        plan = build_trade_plan(close, sma20, atr, df, profile=profile)
        return {
            "ticker": ticker.upper(),
            "profile": profile,
            "current_price": close,
            **trade_plan_to_dict(plan),
        }

    async def get_advice(self, ticker: str, user_id: Optional[int] = None) -> dict[str, Any]:
        _, fused = await self._resolve_signal(ticker)
        advice = await self._llm.advise(fused, user_id=user_id)
        return {"signal": fused, "advice": advice, "user_id": user_id}

    async def ask_question(self, question: str, user_id: Optional[int] = None, ticker_context: str = "") -> dict[str, Any]:
        answer = await self._llm.answer_question(
            question=question,
            user_id=user_id,
            ticker_context=ticker_context,
        )
        return {
            "answer": answer,
            "user_id": user_id,
            "risk_profile": "balanced",
        }

    async def get_news(self, limit: int = 20) -> list[dict[str, Any]]:
        result = await self.db.execute(select(News).order_by(News.published_at.desc()).limit(limit))
        news_list = result.scalars().all()
        return [
            {
                "id": n.id,
                "title": n.title,
                "summary": n.summary[:300] if n.summary else "",
                "source": n.source_name,
                "url": n.url,
                "published_at": n.published_at.isoformat() if n.published_at else None,
            }
            for n in news_list
        ]

    async def get_geo_risk(self, days: int = 30) -> list[dict[str, Any]]:
        cutoff = date.today() - timedelta(days=days)
        result = await self.db.execute(select(GeoRiskScore).where(GeoRiskScore.date >= cutoff).order_by(GeoRiskScore.date))
        scores = result.scalars().all()
        return [
            {
                "date": s.date.isoformat(),
                "score": s.score,
                "components": s.components_json,
            }
            for s in scores
        ]

    async def get_macro(self) -> Any:
        from src.collectors.macro import MacroCollector

        return await MacroCollector.latest_values_async(self.db)

    async def get_sector_performance(self, days: int = 30) -> Any:
        from src.analysis.sector import sector_analyzer

        return await sector_analyzer.compute_sector_performance_async(self.db, days=days)

    async def get_sector_correlation(self, days: int = 90) -> Any:
        from src.analysis.sector import sector_analyzer

        return await sector_analyzer.compute_sector_correlation_async(self.db, days=days)

    async def get_sector_volatility(self, days: int = 30) -> Any:
        from src.analysis.sector import sector_analyzer

        return await sector_analyzer.compute_sector_volatility_async(self.db, days=days)

    async def get_price_target_alerts(self) -> list[dict[str, Any]]:
        alerts = self._notifications.check_price_targets()
        return [
            {
                "ticker": a.ticker,
                "current_price": a.current_price,
                "target_price": a.target_price,
                "target_type": a.target_type,
                "triggered_pct": a.triggered_pct,
            }
            for a in alerts
        ]

    async def get_divergence_alerts(self, ticker: str) -> list[dict[str, Any]]:
        result = await self.db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(404, "Instrument not found")

        cutoff = date.today() - timedelta(days=90)
        price_result = await self.db.execute(
            select(Price).where(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date)
        )
        prices = price_result.scalars().all()
        closes = [float(p.close) for p in prices if p.close]

        ind_result = await self.db.execute(
            select(Indicator).where(Indicator.instrument_id == inst.id, Indicator.date >= cutoff).order_by(Indicator.date)
        )
        indicators = ind_result.scalars().all()
        rsi_vals = [float(i.rsi) for i in indicators if i.rsi is not None]
        macd_vals = [float(i.macd_hist) for i in indicators if i.macd_hist is not None]

        alerts = self._notifications.check_divergence(ticker, closes, rsi_vals, macd_vals)
        return [
            {"ticker": a.ticker, "divergence_type": a.divergence_type, "indicator": a.indicator, "strength": a.strength}
            for a in alerts
        ]

    async def get_rebalance_alerts(self) -> list[dict[str, Any]]:
        alerts = await self._notifications.check_rebalance_async()
        return [
            {
                "ticker": a.ticker,
                "current_pct": a.current_pct,
                "target_pct": a.target_pct,
                "deviation_pct": a.deviation_pct,
                "reason": a.reason,
            }
            for a in alerts
        ]
