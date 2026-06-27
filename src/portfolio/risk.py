import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.db.models import Price

logger = logging.getLogger(__name__)


def item_risk(item: dict[str, Any], db: Session, capital: float = 100_000) -> dict[str, Any]:
    prices = db.query(Price).filter_by(instrument_id=item["id"]).order_by(Price.date.desc()).limit(60).all()
    if len(prices) < 10:
        return {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    close_vals = [float(p.close) for p in prices if p.close]
    if len(close_vals) < 10:
        return {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    return _compute_risk_from_closes(close_vals, item, capital)


async def item_risk_async(item: dict[str, Any], db: AsyncSession, capital: float = 100_000) -> dict[str, Any]:
    result = await db.execute(
        select(Price).where(Price.instrument_id == item["id"]).order_by(Price.date.desc()).limit(60)
    )
    prices = result.scalars().all()
    if len(prices) < 10:
        return {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    close_vals = [float(p.close) for p in prices if p.close]
    if len(close_vals) < 10:
        return {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    return _compute_risk_from_closes(close_vals, item, capital)



def _compute_risk_from_closes(close_vals: list[float], item: dict[str, Any], capital: float) -> dict[str, Any]:
    from src.trading.risk.manager import (
        compute_concentration_limit,
        compute_position_size,
        compute_risk_score,
        compute_stop_loss,
        compute_var,
    )

    var = compute_var(close_vals)
    last_price = close_vals[0]

    stop = compute_stop_loss(last_price, None)
    sizing = compute_position_size(
        capital=capital,
        price=last_price,
        risk_per_trade_pct=2.0,
        stop_loss_pct=stop["stop_loss_pct"] if stop else None,
    )
    conc = compute_concentration_limit(capital, last_price, max_position_pct=20.0)
    risk_score = compute_risk_score(
        var.get("var_95", 0) or 0,
        (abs(stop["stop_loss_pct"]) if stop else 5.0),
    )

    return {
        "var_95": var.get("var_95", 0.0),
        "var_99": var.get("var_99", 0.0),
        "cvar_95": var.get("cvar_95", 0.0),
        "stop_loss": stop["stop_loss"] if stop else None,
        "stop_loss_pct": stop["stop_loss_pct"] if stop else 0.0,
        "suggested_shares": sizing.get("shares", 0),
        "risk_amount": sizing.get("amount", 0.0),
        "risk_per_trade_pct": 2.0,
        "max_position_shares": conc.get("shares", 0),
        "max_position_amount": conc.get("amount", 0.0),
        "risk_score": risk_score,
    }
