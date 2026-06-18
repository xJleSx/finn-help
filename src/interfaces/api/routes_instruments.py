import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.service import analysis_service
from src.db.models import Indicator, Instrument, Price, Signal, User
from src.interfaces.api.auth import get_current_user, get_db
from src.llm.router import llm

logger = logging.getLogger(__name__)
router = APIRouter(tags=["instruments"])


@router.get("/api/instruments")
async def list_instruments(
    type_filter: Optional[str] = Query(None, alias="type"),
    db: AsyncSession = Depends(get_db),
):
    q = select(Instrument)
    if type_filter:
        q = q.where(Instrument.instrument_type == type_filter)
    q = q.order_by(Instrument.ticker)
    result = await db.execute(q)
    instruments = result.scalars().all()

    output = []
    for inst in instruments:
        price_result = await db.execute(
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


@router.get("/api/instruments/{ticker}")
async def get_instrument(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
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


@router.get("/api/instruments/{ticker}/prices")
async def get_prices(
    ticker: str,
    days: int = Query(365, le=365 * 5),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=days)
    price_result = await db.execute(
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


@router.get("/api/instruments/{ticker}/indicators")
async def get_indicators(
    ticker: str,
    days: int = Query(90),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=days)
    ind_result = await db.execute(
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


async def _resolve_signal(ticker: str, db: AsyncSession) -> tuple[Instrument, dict]:
    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    signal_result = await db.execute(
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
        fused = await analysis_service.analyze_single(db, inst, ticker)
    except ValueError as e:
        raise HTTPException(400, str(e))

    await analysis_service.fusion.save_signal(db, inst.id, fused)
    return inst, fused


@router.get("/api/instruments/{ticker}/signal")
async def get_signal(ticker: str, db: AsyncSession = Depends(get_db)):
    _, fused = await _resolve_signal(ticker, db)
    return fused


@router.get("/api/instruments/{ticker}/advice")
async def get_advice(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    _, fused = await _resolve_signal(ticker, db)
    advice = await llm.advise(fused)
    return {"signal": fused, "advice": advice, "user_id": user.id if user else None}
