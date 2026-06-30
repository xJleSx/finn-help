from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sse_starlette.sse import EventSourceResponse

from src.db.connection import get_session
from src.db.models import Instrument, Signal
from src.interfaces.api.dependencies import get_market_service
from src.interfaces.api.schemas import (
    DivergenceAlert,
    GeoRiskItem,
    NewsItem,
    PriceTargetAlert,
    RebalanceAlert,
)
from src.market.service import MarketService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["market"])


@router.get("/api/news", response_model=list[NewsItem])
async def get_news(
    limit: int = Query(20, le=100),
    svc: MarketService = Depends(get_market_service),
) -> list[dict[str, Any]]:
    return await svc.get_news(limit)


@router.get("/api/geo-risk", response_model=list[GeoRiskItem])
async def get_geo_risk(
    days: int = Query(30),
    svc: MarketService = Depends(get_market_service),
) -> list[dict[str, Any]]:
    return await svc.get_geo_risk(days)


@router.get("/api/macro")
async def get_macro(
    svc: MarketService = Depends(get_market_service),
) -> Any:
    return await svc.get_macro()


@router.get("/api/sectors/performance")
async def get_sector_performance(
    days: int = Query(30, le=365),
    svc: MarketService = Depends(get_market_service),
) -> Any:
    return await svc.get_sector_performance(days)


@router.get("/api/sectors/correlation")
async def get_sector_correlation(
    days: int = Query(90, le=365),
    svc: MarketService = Depends(get_market_service),
) -> Any:
    return await svc.get_sector_correlation(days)


@router.get("/api/sectors/volatility")
async def get_sector_volatility(
    days: int = Query(30, le=365),
    svc: MarketService = Depends(get_market_service),
) -> Any:
    return await svc.get_sector_volatility(days)


@router.get("/api/alerts/price-targets", response_model=list[PriceTargetAlert])
async def get_price_target_alerts(
    svc: MarketService = Depends(get_market_service),
) -> list[dict[str, Any]]:
    return await svc.get_price_target_alerts()


@router.get("/api/alerts/divergence/{ticker}", response_model=list[DivergenceAlert])
async def get_divergence_alerts(
    ticker: str,
    svc: MarketService = Depends(get_market_service),
) -> list[dict[str, Any]]:
    return await svc.get_divergence_alerts(ticker)


@router.get("/api/alerts/rebalance", response_model=list[RebalanceAlert])
async def get_rebalance_alerts(
    svc: MarketService = Depends(get_market_service),
) -> list[dict[str, Any]]:
    return await svc.get_rebalance_alerts()


@router.get("/api/events")
async def event_stream() -> EventSourceResponse:
    async def generate() -> AsyncGenerator[dict[str, str], None]:
        while True:

            def _query_stats() -> dict[str, Any]:
                db = get_session()
                try:
                    inst_count = db.query(Instrument).count()
                    signal_count = db.query(Signal).count()
                    latest_signal = db.query(Signal).order_by(Signal.date.desc()).first()
                    return {
                        "instruments": inst_count,
                        "signals": signal_count,
                        "last_update": latest_signal.date.isoformat() if latest_signal else None,
                        "timestamp": date.today().isoformat(),
                    }
                finally:
                    db.close()

            loop = asyncio.get_running_loop()
            try:
                data = await loop.run_in_executor(None, _query_stats)
                yield {"data": json.dumps(data)}
            except Exception:
                logger.exception("sse_event_error")
            await asyncio.sleep(60)

    return EventSourceResponse(generate())


@router.get("/api/models")
async def list_models() -> Any:
    from src.model_registry import list_models

    return list_models()
