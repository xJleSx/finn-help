from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Instrument, Portfolio, Price, Signal

logger = structlog.get_logger(__name__)


class PortfolioService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_positions(self, user_id: int) -> list[dict[str, Any]]:
        q = select(Portfolio).where(Portfolio.user_id == user_id)
        result = await self.db.execute(q)
        positions = result.scalars().all()

        output = []
        for p in positions:
            inst_result = await self.db.execute(select(Instrument).where(Instrument.id == p.instrument_id))
            inst = inst_result.scalar_one_or_none()
            price_result = await self.db.execute(
                select(Price).where(Price.instrument_id == p.instrument_id).order_by(Price.date.desc()).limit(1)
            )
            last_price = price_result.scalar_one_or_none()
            current_price = last_price.close if last_price else 0
            output.append(
                {
                    "id": p.id,
                    "ticker": inst.ticker if inst else "?",
                    "quantity": float(p.quantity),
                    "avg_price": float(p.avg_price) if p.avg_price else 0,
                    "current_price": float(current_price),
                    "value": float(current_price * p.quantity) if current_price and p.quantity else 0,
                    "profit_pct": round(((current_price / p.avg_price) - 1) * 100, 2)
                    if current_price and p.avg_price
                    else 0,
                }
            )
        return output

    async def add_position(self, user_id: int, ticker: str, quantity: float, avg_price: Optional[float] = None) -> dict[str, str]:
        result = await self.db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(404, "Instrument not found")

        existing_result = await self.db.execute(
            select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.instrument_id == inst.id)
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            existing.quantity += quantity
            if avg_price:
                existing.avg_price = avg_price
        else:
            pos = Portfolio(user_id=user_id, instrument_id=inst.id, quantity=quantity, avg_price=avg_price)
            self.db.add(pos)
        await self.db.commit()
        return {"status": "ok"}

    async def allocate(self, capital: float) -> Any:
        from src.portfolio.allocator import allocator

        try:
            return await allocator.allocate_async(capital, db=self.db)
        except Exception as e:
            logger.exception("allocation_failed", capital=capital)
            raise HTTPException(500, f"Allocation failed: {e}")

    async def get_positions_for_csv(self, user_id: Optional[int]) -> list[dict[str, Any]]:
        from src.db.models import Portfolio

        q = select(Portfolio)
        if user_id:
            q = q.where(Portfolio.user_id == user_id)
        result = await self.db.execute(q)
        positions_raw = result.scalars().all()

        positions = []
        for p in positions_raw:
            inst_result = await self.db.execute(select(Instrument).where(Instrument.id == p.instrument_id))
            inst = inst_result.scalar_one_or_none()
            price_result = await self.db.execute(
                select(Price).where(Price.instrument_id == p.instrument_id).order_by(Price.date.desc()).limit(1)
            )
            last_price = price_result.scalar_one_or_none()
            current_price = last_price.close if last_price else 0
            positions.append(
                {
                    "ticker": inst.ticker if inst else "?",
                    "name": inst.full_name if inst else "",
                    "quantity": float(p.quantity),
                    "avg_price": float(p.avg_price) if p.avg_price else 0,
                    "current_price": float(current_price),
                    "value": float(current_price * p.quantity) if current_price and p.quantity else 0,
                    "profit_pct": round(((current_price / p.avg_price) - 1) * 100, 2)
                    if current_price and p.avg_price
                    else 0,
                }
            )
        return positions

    async def get_signals_for_csv(self, limit: int = 50) -> list[dict[str, Any]]:
        from src.reports import generate_signals_csv

        result = await self.db.execute(select(Signal).order_by(Signal.date.desc()).limit(limit))
        signals = result.scalars().all()
        return [s.fused_json or {} for s in signals if s.fused_json]

    async def get_sectors_for_csv(self) -> tuple[Any, Any]:
        from src.analysis.sector import sector_analyzer

        perf = await sector_analyzer.compute_sector_performance_async(self.db)
        vol = await sector_analyzer.compute_sector_volatility_async(self.db)
        return perf, vol
