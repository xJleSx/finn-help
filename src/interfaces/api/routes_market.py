import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.db.connection import close_session, get_session
from src.db.models import GeoRiskScore, Indicator, Instrument, News, Price, Signal
from src.interfaces.api.auth import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["market"])


@router.get("/api/news")
async def get_news(limit: int = Query(20, le=100), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(News).order_by(News.published_at.desc()).limit(limit))
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


@router.get("/api/geo-risk")
async def get_geo_risk(days: int = Query(30), db: AsyncSession = Depends(get_db)):
    cutoff = date.today() - timedelta(days=days)
    result = await db.execute(select(GeoRiskScore).where(GeoRiskScore.date >= cutoff).order_by(GeoRiskScore.date))
    scores = result.scalars().all()
    return [
        {
            "date": s.date.isoformat(),
            "score": s.score,
            "components": s.components_json,
        }
        for s in scores
    ]


@router.get("/api/macro")
async def get_macro(db: AsyncSession = Depends(get_db)):
    from src.collectors.macro import MacroCollector

    return await MacroCollector.latest_values_async(db)


@router.get("/api/sectors/performance")
async def get_sector_performance(days: int = Query(30, le=365), db: AsyncSession = Depends(get_db)):
    from src.analysis.sector import sector_analyzer

    return await sector_analyzer.compute_sector_performance_async(db, days=days)


@router.get("/api/sectors/correlation")
async def get_sector_correlation(days: int = Query(90, le=365), db: AsyncSession = Depends(get_db)):
    from src.analysis.sector import sector_analyzer

    return await sector_analyzer.compute_sector_correlation_async(db, days=days)


@router.get("/api/sectors/volatility")
async def get_sector_volatility(days: int = Query(30, le=365), db: AsyncSession = Depends(get_db)):
    from src.analysis.sector import sector_analyzer

    return await sector_analyzer.compute_sector_volatility_async(db, days=days)


@router.get("/api/alerts/price-targets")
async def get_price_target_alerts():
    from src.notifications.service import notification_service

    alerts = []
    for a in notification_service.check_price_targets():
        alerts.append(
            {
                "ticker": a.ticker,
                "current_price": a.current_price,
                "target_price": a.target_price,
                "target_type": a.target_type,
                "triggered_pct": a.triggered_pct,
            }
        )
    return alerts


@router.get("/api/alerts/divergence/{ticker}")
async def get_divergence_alerts(ticker: str, db: AsyncSession = Depends(get_db)):
    from src.notifications.service import notification_service

    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Instrument not found")

    cutoff = date.today() - timedelta(days=90)
    price_result = await db.execute(
        select(Price).where(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date)
    )
    prices = price_result.scalars().all()
    closes = [p.close for p in prices if p.close]

    ind_result = await db.execute(
        select(Indicator).where(Indicator.instrument_id == inst.id, Indicator.date >= cutoff).order_by(Indicator.date)
    )
    indicators = ind_result.scalars().all()
    rsi_vals = [i.rsi for i in indicators if i.rsi is not None]
    macd_vals = [i.macd_hist for i in indicators if i.macd_hist is not None]

    alerts = notification_service.check_divergence(ticker, closes, rsi_vals, macd_vals)
    return [
        {"ticker": a.ticker, "divergence_type": a.divergence_type, "indicator": a.indicator, "strength": a.strength}
        for a in alerts
    ]


@router.get("/api/alerts/rebalance")
async def get_rebalance_alerts(db: AsyncSession = Depends(get_db)):
    from src.notifications.service import notification_service

    alerts = notification_service.check_rebalance_async(db)
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


@router.get("/api/events")
async def event_stream():
    async def generate():
        while True:
            db = get_session()
            try:
                inst_count = db.query(Instrument).count()
                signal_count = db.query(Signal).count()
                latest_signal = db.query(Signal).order_by(Signal.date.desc()).first()
                yield {
                    "data": json.dumps({
                        "instruments": inst_count,
                        "signals": signal_count,
                        "last_update": latest_signal.date.isoformat() if latest_signal else None,
                        "timestamp": date.today().isoformat(),
                    })
                }
            except Exception:
                logger.exception("SSE event error")
            finally:
                db.close()
                close_session()
            await asyncio.sleep(60)

    return EventSourceResponse(generate())


@router.get("/api/models")
async def list_models():
    from src.model_registry import list_models

    return list_models()
