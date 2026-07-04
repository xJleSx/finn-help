from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from src.db.models import User
from src.interfaces.api.auth import get_current_user
from src.interfaces.api.dependencies import get_market_service, get_market_service_readonly
from src.interfaces.api.rate_limiter import limiter
from src.interfaces.api.schemas import (
    AdviceResponse,
    AskResponse,
    IndicatorData,
    InstrumentDetail,
    InstrumentListItem,
    PriceData,
    TradePlanResponse,
)
from src.market.service import MarketService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["instruments"])


class AskBody(BaseModel):
    question: str
    ticker_context: str = ""


@router.get("/api/instruments", response_model=list[InstrumentListItem])
async def list_instruments(
    type_filter: Optional[str] = Query(None, alias="type"),
    svc: MarketService = Depends(get_market_service_readonly),
) -> list[dict[str, Any]]:
    return await svc.list_instruments(type_filter)


@router.get("/api/instruments/{ticker}", response_model=InstrumentDetail)
async def get_instrument(
    ticker: str,
    svc: MarketService = Depends(get_market_service_readonly),
) -> dict[str, Any]:
    return await svc.get_instrument(ticker)


@router.get("/api/instruments/{ticker}/prices", response_model=list[PriceData])
async def get_prices(
    ticker: str,
    days: int = Query(365, le=365 * 5),
    svc: MarketService = Depends(get_market_service_readonly),
) -> list[dict[str, Any]]:
    return await svc.get_prices(ticker, days)


@router.get("/api/instruments/{ticker}/indicators", response_model=list[IndicatorData])
async def get_indicators(
    ticker: str,
    days: int = Query(90),
    svc: MarketService = Depends(get_market_service_readonly),
) -> list[dict[str, Any]]:
    return await svc.get_indicators(ticker, days)


@router.get("/api/instruments/{ticker}/signal")
async def get_signal(
    ticker: str,
    svc: MarketService = Depends(get_market_service_readonly),
) -> Any:
    return await svc.get_signal(ticker)


@router.get("/api/instruments/{ticker}/trade-plan", response_model=TradePlanResponse)
async def get_trade_plan(
    ticker: str,
    profile: str = Query("balanced"),
    svc: MarketService = Depends(get_market_service_readonly),
) -> dict[str, Any]:
    return await svc.get_trade_plan(ticker, profile)


@router.get("/api/instruments/{ticker}/advice", response_model=AdviceResponse)
async def get_advice(
    ticker: str,
    user: Optional[User] = Depends(get_current_user),
    svc: MarketService = Depends(get_market_service_readonly),
) -> dict[str, Any]:
    return await svc.get_advice(ticker, int(user.id) if user else None)


@router.post("/api/ask", response_model=AskResponse)
@limiter.limit("30/minute")
async def ask_question(
    request: Request,
    body: AskBody,
    user: Optional[User] = Depends(get_current_user),
    svc: MarketService = Depends(get_market_service),
) -> dict[str, Any]:
    return await svc.ask_question(
        question=body.question,
        user_id=int(user.id) if user else None,
        ticker_context=body.ticker_context,
    )
