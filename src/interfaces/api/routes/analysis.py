from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.alerts.engine import AlertEngine
from src.analysis.ml.news_impact import NewsImpactModel
from src.analysis.scenario.engine import ScenarioEngine
from src.db.connection import get_session
from src.db.models import Instrument, News, NewsInstrument
from src.interfaces.api.auth import get_db
from src.interfaces.api.schemas import (
    AlertResponse,
    ImpactAttributionResponse,
    ScenarioResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])


def _run_scenario_sync(user_id: int) -> dict[str, Any]:
    db = get_session()
    try:
        engine = ScenarioEngine()
        engine.from_portfolio(db, user_id)
        engine.load_prices(db)
        return engine.run_all()
    finally:
        db.close()


@router.get("/api/analysis/scenario", response_model=ScenarioResponse)
async def run_scenario_analysis(
    user_id: int = Query(0),
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _run_scenario_sync, user_id)
        return result
    except Exception as e:
        logger.exception("Scenario analysis failed for user_id=%s", user_id)
        raise HTTPException(500, f"Scenario analysis failed: {e}")


def _custom_scenario_sync(ticker: str, shock_pct: float, user_id: int) -> dict[str, Any]:
    db = get_session()
    try:
        engine = ScenarioEngine()
        engine.from_portfolio(db, user_id)
        result = engine.run_custom_shock(ticker, shock_pct)
        if result is None:
            raise ValueError(f"Ticker {ticker} not found in portfolio")
        return {
            "name": result.name,
            "total_before": result.total_before,
            "total_after": result.total_after,
            "loss": result.loss,
            "loss_pct": result.loss_pct,
            "details": result.details,
            "scenario_type": result.scenario_type,
        }
    finally:
        db.close()


@router.get("/api/analysis/scenario/custom")
async def custom_scenario(
    ticker: str = Query(...),
    shock_pct: float = Query(...),
    user_id: int = Query(0),
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _custom_scenario_sync, ticker, shock_pct, user_id)
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Custom scenario failed for ticker=%s", ticker)
        raise HTTPException(500, f"Custom scenario failed: {e}")


@router.get("/api/analysis/news/{news_id}/impact", response_model=ImpactAttributionResponse)
async def news_impact_attribution(
    news_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    news_result = await db.execute(select(News).where(News.id == news_id))
    article = news_result.scalar_one_or_none()
    if not article:
        raise HTTPException(404, "News article not found")

    ticker_result = await db.execute(
        select(Instrument.ticker)
        .join(NewsInstrument, NewsInstrument.instrument_id == Instrument.id)
        .where(NewsInstrument.news_id == news_id)
    )
    tickers = [r[0] for r in ticker_result.all()]
    if not tickers:
        return {"news_id": news_id, "ticker": "", "feature_importances": []}

    ticker = tickers[0]
    model = NewsImpactModel(ticker)
    for h in model.horizons:
        try:
            model.load(h)
        except (ValueError, FileNotFoundError):
            continue

    top_features = []
    for h in model.horizons:
        m = model._models.get(h)
        if m is not None:
            fi = model._feature_importance(m)
            top_features.extend(fi)

    seen = set()
    unique_features = []
    for fi in top_features:
        if fi["feature"] not in seen:
            seen.add(fi["feature"])
            unique_features.append(fi)

    return {
        "news_id": news_id,
        "ticker": ticker,
        "feature_importances": unique_features[:10],
    }


def _get_alerts_sync(user_id: int, limit: int) -> list[dict[str, Any]]:
    db = get_session()
    try:
        engine = AlertEngine()
        articles = db.execute(
            select(News).order_by(News.published_at.desc()).limit(200)
        ).scalars().all()
        alerts = engine.process_portfolio_articles(db, articles, user_id)
        return alerts[:limit]
    finally:
        db.close()


@router.get("/api/alerts", response_model=AlertResponse)
async def get_alerts(
    user_id: int = Query(...),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        alerts = await loop.run_in_executor(None, _get_alerts_sync, user_id, limit)
        return {"alerts": alerts}
    except Exception as e:
        logger.exception("Failed to get alerts for user_id=%s", user_id)
        raise HTTPException(500, f"Failed to get alerts: {e}")


def _refresh_alerts_sync(user_id: int) -> int:
    db = get_session()
    try:
        engine = AlertEngine()
        engine.train_anomaly(db)
        articles = db.execute(
            select(News).order_by(News.published_at.desc()).limit(200)
        ).scalars().all()
        alerts = engine.process_portfolio_articles(db, articles, user_id)
        return len(alerts)
    finally:
        db.close()


@router.post("/api/alerts/refresh")
async def refresh_alerts(
    user_id: int = Query(0),
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        count = await loop.run_in_executor(None, _refresh_alerts_sync, user_id)
        return {"new_alerts": count}
    except Exception as e:
        logger.exception("Alert refresh failed")
        raise HTTPException(500, f"Alert refresh failed: {e}")
