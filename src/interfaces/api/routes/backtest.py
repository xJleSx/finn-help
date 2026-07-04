from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.analysis.backtest import BacktestConfig, backtest_allocation
from src.analysis.personal_backtest import run_personal_backtest
from src.analysis.sensitivity import commission_sensitivity, slippage_sensitivity
from src.analysis.walk_forward_analysis import WalkForwardConfig, run_walk_forward
from src.db.connection import get_session
from src.db.models import Instrument, Price, User
from src.interfaces.api.auth import require_user
from src.trading.metrics import compute_metrics

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["backtest"])


@router.get("/api/backtest/run")
async def run_backtest(
    capital: float = Query(100_000, ge=1000),
    lookback_days: int = Query(365, ge=30, le=3650),
    slippage_bps: int = Query(5, ge=0, le=100),
    commission_pct: float = Query(0.0004, ge=0, le=0.1),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    try:
        import asyncio

        loop = asyncio.get_running_loop()

        def _run() -> dict[str, Any]:
            config = BacktestConfig(
                capital=capital,
                lookback_days=lookback_days,
                slippage_bps=slippage_bps,
                commission_pct=commission_pct,
            )
            result = backtest_allocation(capital=capital, lookback_days=lookback_days, config=config)
            return {
                "capital": result.capital,
                "total_return": result.portfolio_return,
                "benchmark_return": result.benchmark_return,
                "alpha": result.alpha,
                "sharpe": result.portfolio_sharpe,
                "sortino": result.portfolio_sortino,
                "calmar": result.portfolio_calmar,
                "max_drawdown": result.portfolio_max_dd,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "n_dates": len(result.dates),
                "n_trades": result.trades,
                "total_commission": result.total_commission,
                "total_slippage": result.total_slippage,
                "regime": result.regime.regime if result.regime else None,
                "monte_carlo": {
                    "mean_return": result.monte_carlo.mean_return,
                    "var_95": result.monte_carlo.var_95,
                    "cvar_95": result.monte_carlo.cvar_95,
                    "upside_pct": result.monte_carlo.upside_pct,
                }
                if result.monte_carlo
                else None,
            }

        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.exception("backtest_failed")
        raise HTTPException(500, f"Backtest failed: {e}")


class PersonalBacktestBody(BaseModel):
    tickers: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    capital: float = 100_000
    commission_pct: float | None = None
    slippage_pct: float | None = None
    use_tbank_fees: bool = False


@router.post("/api/backtest/personal")
async def personal_backtest(
    body: PersonalBacktestBody,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    try:
        import asyncio

        loop = asyncio.get_running_loop()

        def _run() -> dict[str, Any]:
            start = date.fromisoformat(body.start_date) if body.start_date else None
            end = date.fromisoformat(body.end_date) if body.end_date else None
            result = run_personal_backtest(
                tickers=body.tickers,
                start=start,
                end=end,
                capital=body.capital,
                commission_pct=body.commission_pct,
                slippage_pct=body.slippage_pct,
                use_tbank_fees=body.use_tbank_fees,
            )
            return {
                "tickers": result.tickers,
                "start_date": str(result.start_date),
                "end_date": str(result.end_date),
                "initial_capital": result.initial_capital,
                "final_capital": result.final_capital,
                "total_return": result.total_return,
                "benchmark_return": result.benchmark_return,
                "alpha": result.alpha,
                "sharpe": result.sharpe,
                "sortino": result.sortino,
                "calmar": result.calmar,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "total_commission": result.total_commission,
                "total_slippage": result.total_slippage,
                "n_trades": result.n_trades,
                "equity_curve": result.equity_curve,
                "walk_forward": [
                    {
                        "fold": f.fold,
                        "train_start": str(f.train_start),
                        "train_end": str(f.train_end),
                        "test_start": str(f.test_start),
                        "test_end": str(f.test_end),
                        "portfolio_return": f.portfolio_return,
                        "benchmark_return": f.benchmark_return,
                        "sharpe": f.sharpe,
                        "max_drawdown": f.max_drawdown,
                        "trades": f.trades,
                    }
                    for f in result.walk_forward
                ],
            }

        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.exception("personal_backtest_failed")
        raise HTTPException(500, f"Personal backtest failed: {e}")


@router.get("/api/backtest/walk-forward")
async def walk_forward(
    ticker: str = Query(..., description="Ticker symbol"),
    n_splits: int = Query(5, ge=2, le=20),
    gap: int = Query(20, ge=5, le=100),
    min_train_days: int = Query(252, ge=60, le=1000),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    try:
        import asyncio

        loop = asyncio.get_running_loop()

        def _run() -> dict[str, Any]:
            db = get_session()
            try:
                inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
                if not inst:
                    raise HTTPException(404, f"Instrument {ticker} not found")
                prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.asc()).all()
                price_vals = [float(p.close) for p in prices if p.close]
                if len(price_vals) < 100:
                    raise HTTPException(400, f"Not enough price data for {ticker}")
                start_date = str(prices[0].date) if prices[0].date else ""
                end_date = str(prices[-1].date) if prices[-1].date else ""
            finally:
                db.close()

            config = WalkForwardConfig(
                n_splits=n_splits,
                gap=gap,
                min_train_size=min_train_days,
            )
            result = run_walk_forward(
                prices=price_vals,
                config=config,
                ticker=ticker.upper(),
                start_date=start_date,
                end_date=end_date,
            )
            return {
                "ticker": result.ticker,
                "start_date": result.start_date,
                "end_date": result.end_date,
                "config": {
                    "n_splits": result.config.n_splits,
                    "gap": result.config.gap,
                    "min_train_size": result.config.min_train_size,
                },
                "avg_test_return": result.avg_test_return,
                "avg_test_sharpe": result.avg_test_sharpe,
                "avg_test_max_dd": result.avg_test_max_dd,
                "stability": result.stability,
                "oos_sharpe": result.oos_sharpe,
                "folds": [
                    {
                        "fold": f.fold,
                        "train_sharpe": f.train_metrics.sharpe,
                        "train_return": f.train_metrics.total_return,
                        "test_sharpe": f.test_metrics.sharpe,
                        "test_return": f.test_metrics.total_return,
                        "test_max_dd": f.test_metrics.max_drawdown,
                    }
                    for f in result.folds
                ],
            }

        return await loop.run_in_executor(None, _run)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("walk_forward_failed")
        raise HTTPException(500, f"Walk-forward analysis failed: {e}")


@router.get("/api/backtest/sensitivity")
async def sensitivity_analysis(
    ticker: str = Query(..., description="Ticker symbol"),
    param: str = Query("commission", description="commission or slippage"),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    try:
        import asyncio

        loop = asyncio.get_running_loop()

        def _run() -> dict[str, Any]:
            db = get_session()
            try:
                inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
                if not inst:
                    raise HTTPException(404, f"Instrument {ticker} not found")
                prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.asc()).all()
                equity = [float(p.close) for p in prices if p.close]
                if len(equity) < 20:
                    raise HTTPException(400, f"Not enough price data for {ticker}")
            finally:
                db.close()

            if param == "commission":
                result = commission_sensitivity(equity)
            else:
                result = slippage_sensitivity(equity)
            return result.to_dict()

        return await loop.run_in_executor(None, _run)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sensitivity_failed")
        raise HTTPException(500, f"Sensitivity analysis failed: {e}")


@router.get("/api/backtest/ticker-metrics")
async def ticker_metrics(
    ticker: str = Query(..., description="Ticker symbol"),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    try:
        import asyncio

        loop = asyncio.get_running_loop()

        def _run() -> dict[str, Any]:
            db = get_session()
            try:
                inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
                if not inst:
                    raise HTTPException(404, f"Instrument {ticker} not found")
                prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.asc()).all()
                equity = [float(p.close) for p in prices if p.close]
                if len(equity) < 20:
                    return {"ticker": ticker, "error": "Not enough data"}
                metrics = compute_metrics(equity, annual_factor=252)
                return {
                    "ticker": ticker,
                    "metrics": metrics.to_dict(),
                    "current_price": equity[-1],
                    "start_price": equity[0],
                    "n_days": len(equity),
                }
            finally:
                db.close()

        return await loop.run_in_executor(None, _run)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ticker_metrics_failed")
        raise HTTPException(500, f"Ticker metrics failed: {e}")
