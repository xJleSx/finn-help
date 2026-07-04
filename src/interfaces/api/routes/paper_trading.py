from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.db.models import User
from src.interfaces.api.auth import require_user
from src.trading.paper import DEFAULT_INITIAL_CAPITAL, PaperTradingEngine

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["paper-trading"])


def get_paper_engine(user_id: int) -> PaperTradingEngine:
    return PaperTradingEngine(user_id=user_id)


@router.get("/api/paper/status")
async def paper_status(
    user: User = Depends(require_user),
) -> dict[str, Any]:
    engine = get_paper_engine(user.id)
    state = engine.get_state()
    equity = state.total_equity()
    return {
        "balance": state.balance,
        "initial_capital": state.initial_capital,
        "total_equity": equity,
        "total_return_pct": ((equity / state.initial_capital) - 1) if state.initial_capital > 0 else 0.0,
        "positions": [
            {"ticker": p.ticker, "quantity": p.quantity, "avg_price": p.avg_price, "value": p.quantity * p.avg_price}
            for p in sorted(state.positions.values(), key=lambda x: x.quantity * x.avg_price, reverse=True)
        ],
        "n_trades": len(state.trades),
        "start_time": state.start_time,
    }


class PaperOrderBody(BaseModel):
    ticker: str
    direction: str  # BUY / SELL
    quantity: float
    price: float | None = None
    reason: str = ""


@router.post("/api/paper/order")
async def paper_place_order(
    body: PaperOrderBody,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    engine = get_paper_engine(user.id)
    result = engine.execute_order(
        ticker=body.ticker,
        direction=body.direction,
        quantity=body.quantity,
        price=body.price,
        reason=body.reason,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error", "Order failed"))
    return result


@router.get("/api/paper/orders")
async def paper_order_history(
    user: User = Depends(require_user),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    engine = get_paper_engine(user.id)
    trades = engine.get_trades(limit=limit)
    return {"trades": trades, "total": len(trades)}


@router.post("/api/paper/reset")
async def paper_reset(
    user: User = Depends(require_user),
    initial_capital: float = Query(DEFAULT_INITIAL_CAPITAL, ge=1000),
) -> dict[str, Any]:
    engine = get_paper_engine(user.id)
    state = engine.reset(initial_capital=initial_capital)
    return {"status": "ok", "balance": state.balance, "initial_capital": state.initial_capital}


@router.get("/api/paper/equity-curve")
async def paper_equity_curve(
    user: User = Depends(require_user),
) -> dict[str, Any]:
    engine = get_paper_engine(user.id)
    history = engine.get_equity_history()
    return {"equity_curve": history}


@router.get("/api/paper/metrics")
async def paper_metrics(
    user: User = Depends(require_user),
) -> dict[str, Any]:
    engine = get_paper_engine(user.id)
    metrics = engine.get_metrics()
    return metrics.to_dict()
