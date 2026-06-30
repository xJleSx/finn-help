from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from src.db.models import User
from src.interfaces.api.auth import get_current_user, require_user
from src.interfaces.api.dependencies import get_portfolio_service
from src.interfaces.api.schemas import AllocationResponse, PortfolioAddResponse, PortfolioPosition
from src.portfolio.service import PortfolioService
from src.reports import generate_portfolio_csv, generate_signals_csv, generate_sector_report_csv

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["portfolio"])


class AllocateBody(BaseModel):
    capital: float = 50000.0


@router.get("/api/portfolio", response_model=list[PortfolioPosition])
async def get_portfolio(
    user: User = Depends(require_user),
    svc: PortfolioService = Depends(get_portfolio_service),
) -> list[dict[str, Any]]:
    return await svc.get_positions(user.id)


class AddPositionBody(BaseModel):
    ticker: str
    quantity: float
    avg_price: Optional[float] = None


@router.post("/api/portfolio/add", response_model=PortfolioAddResponse)
async def add_portfolio_position(
    body: AddPositionBody,
    user: User = Depends(require_user),
    svc: PortfolioService = Depends(get_portfolio_service),
) -> dict[str, str]:
    return await svc.add_position(user.id, body.ticker.upper(), body.quantity, body.avg_price)


@router.post("/api/portfolio/allocate", response_model=AllocationResponse)
async def allocate_portfolio(
    body: AllocateBody,
    user: User = Depends(require_user),
    svc: PortfolioService = Depends(get_portfolio_service),
) -> Any:
    return await svc.allocate(body.capital)


@router.get("/api/reports/portfolio")
async def report_portfolio_csv(
    user: Optional[User] = Depends(get_current_user),
    svc: PortfolioService = Depends(get_portfolio_service),
) -> PlainTextResponse:
    positions = await svc.get_positions_for_csv(user.id if user else None)
    csv_content = generate_portfolio_csv(positions)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


@router.get("/api/reports/signals")
async def report_signals_csv(svc: PortfolioService = Depends(get_portfolio_service)) -> PlainTextResponse:
    signal_list = await svc.get_signals_for_csv()
    csv_content = generate_signals_csv(signal_list)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=signals.csv"},
    )


@router.get("/api/reports/sectors")
async def report_sectors_csv(svc: PortfolioService = Depends(get_portfolio_service)) -> PlainTextResponse:
    perf, vol = await svc.get_sectors_for_csv()
    csv_content = generate_sector_report_csv(perf, vol)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sectors.csv"},
    )
