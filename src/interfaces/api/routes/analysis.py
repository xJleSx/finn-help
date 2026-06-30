from __future__ import annotations

import asyncio
from typing import Any

import structlog
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

logger = structlog.get_logger(__name__)
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
        logger.exception("scenario_failed", user_id=user_id)
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
        logger.exception("custom_scenario_failed", ticker=ticker)
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
        logger.exception("alerts_get_failed", user_id=user_id)
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
        logger.exception("alert_refresh_failed")
        raise HTTPException(500, f"Alert refresh failed: {e}")



# ── Risk explorer endpoints ──────────────────────────────────────────────

def _risk_portfolio_summary_sync(user_id: int) -> dict[str, Any]:
    from src.analysis.risk_explorer import RiskExplorer

    db = get_session()
    try:
        explorer = RiskExplorer()
        return explorer.portfolio_risk_summary(db, user_id)
    finally:
        db.close()


def _risk_ticker_deep_dive_sync(ticker: str, user_id: int) -> dict[str, Any]:
    from src.analysis.risk_explorer import RiskExplorer

    db = get_session()
    try:
        explorer = RiskExplorer()
        return explorer.ticker_deep_dive(db, ticker, user_id)
    finally:
        db.close()


@router.get("/api/risk/portfolio")
async def risk_portfolio_summary(
    user_id: int = Query(0),
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _risk_portfolio_summary_sync, user_id)
        return result
    except Exception as e:
        logger.exception("risk_portfolio_summary_failed", user_id=user_id)
        raise HTTPException(500, f"Risk portfolio summary failed: {e}")



@router.get("/api/risk/deep-dive/{ticker}")
async def risk_ticker_deep_dive(
    ticker: str,
    user_id: int = Query(0),
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _risk_ticker_deep_dive_sync, ticker, user_id)
        return result
    except Exception as e:
        logger.exception("risk_deep_dive_failed", ticker=ticker)
        raise HTTPException(500, f"Risk deep dive failed: {e}")



# ── Causal inference endpoint ────────────────────────────────────────────

def _causal_analysis_sync(ticker: str, target_ticker: str | None) -> dict[str, Any]:
    from src.analysis.inference.causal import GrangerCausality, InstrumentCausalGraph

    db = get_session()
    try:
        if target_ticker:
            result = GrangerCausality().test_news_causality(db, ticker, target_ticker)
            return {"ticker": ticker, "target": target_ticker, "result": result}
        graph = InstrumentCausalGraph()
        graph.build_from_sector(db, ticker)
        return {
            "ticker": ticker,
            "influencers": graph.get_influencers(ticker, top_n=5),
        }
    finally:
        db.close()


@router.get("/api/analysis/causal/{ticker}")
async def causal_analysis(
    ticker: str,
    target: str | None = Query(None, alias="target"),
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _causal_analysis_sync, ticker, target)
        return result
    except Exception as e:
        logger.exception("causal_analysis_failed", ticker=ticker)
        raise HTTPException(500, f"Causal analysis failed: {e}")

