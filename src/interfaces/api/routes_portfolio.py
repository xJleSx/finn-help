import logging
from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Instrument, Price, Signal, User
from src.interfaces.api.auth import get_current_user, get_db, require_user
from src.interfaces.api.schemas import AllocationResponse, PortfolioAddResponse, PortfolioPosition

logger = logging.getLogger(__name__)
router = APIRouter(tags=["portfolio"])


class AllocateBody(BaseModel):
    capital: float = 50000.0


@router.get("/api/portfolio", response_model=list[PortfolioPosition])
async def get_portfolio(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> list[dict[str, Any]]:
    from src.db.models import Portfolio

    q = select(Portfolio).where(Portfolio.user_id == user.id)
    result = await db.execute(q)
    positions = result.scalars().all()

    output = []
    for p in positions:
        inst_result = await db.execute(select(Instrument).where(Instrument.id == p.instrument_id))
        inst = inst_result.scalar_one_or_none()
        price_result = await db.execute(
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


class AddPositionBody(BaseModel):
    ticker: str
    quantity: float
    avg_price: Optional[float] = None


@router.post("/api/portfolio/add", response_model=PortfolioAddResponse)
async def add_portfolio_position(
    body: AddPositionBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, str]:
    from src.db.models import Portfolio

    result = await db.execute(select(Instrument).where(Instrument.ticker == body.ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    existing_result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.instrument_id == inst.id)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        existing.quantity += body.quantity  # type: ignore[assignment]
        if body.avg_price:
            existing.avg_price = body.avg_price  # type: ignore[assignment]
    else:
        pos = Portfolio(user_id=user.id, instrument_id=inst.id, quantity=body.quantity, avg_price=body.avg_price)
        db.add(pos)
    await db.commit()
    return {"status": "ok"}


@router.post("/api/portfolio/allocate", response_model=AllocationResponse)
async def allocate_portfolio(
    body: AllocateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> Any:
    from src.portfolio.allocator import allocator

    try:
        result = await allocator.allocate_async(body.capital, db=db)
        return result
    except Exception as e:
        logger.exception("Allocation failed for capital=%s", body.capital)
        raise HTTPException(500, f"Allocation failed: {e}")


@router.get("/api/reports/portfolio")
async def report_portfolio_csv(
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
) -> PlainTextResponse:
    from src.db.models import Portfolio
    from src.reports import generate_portfolio_csv

    q = select(Portfolio)
    if user:
        q = q.where(Portfolio.user_id == user.id)
    result = await db.execute(q)
    positions_raw = result.scalars().all()

    positions = []
    for p in positions_raw:
        inst_result = await db.execute(select(Instrument).where(Instrument.id == p.instrument_id))
        inst = inst_result.scalar_one_or_none()
        price_result = await db.execute(
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
    csv_content = generate_portfolio_csv(positions)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


@router.get("/api/reports/signals")
async def report_signals_csv(db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    from src.reports import generate_signals_csv

    result = await db.execute(select(Signal).order_by(Signal.date.desc()).limit(50))
    signals = result.scalars().all()
    signal_list: list[dict[str, Any]] = [cast(dict[str, Any], s.fused_json) or {} for s in signals if s.fused_json]
    csv_content = generate_signals_csv(signal_list)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=signals.csv"},
    )


@router.get("/api/reports/sectors")
async def report_sectors_csv(db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    from src.analysis.sector import sector_analyzer
    from src.reports import generate_sector_report_csv

    perf = await sector_analyzer.compute_sector_performance_async(db)
    vol = await sector_analyzer.compute_sector_volatility_async(db)
    csv_content = generate_sector_report_csv(perf, vol)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sectors.csv"},
    )
