"""Portfolio bonds endpoints — positions, summary, allocation, cash-flow."""

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Instrument, Portfolio, Price, User
from src.interfaces.api.auth import require_user
from src.interfaces.api.dependencies import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["portfolio-bonds"], prefix="/api/portfolio")


@router.get("/bonds")
async def get_portfolio_bonds(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    user_id = user.id

    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.instrument).selectinload(Instrument.bond_offerings))
        .where(Portfolio.user_id == user_id)
    )
    positions = result.scalars().all()

    items: list[dict[str, Any]] = []
    total_value = 0.0
    total_invested = 0.0

    for pos in positions:
        inst = pos.instrument
        if not inst or inst.instrument_type != "bond":
            continue

        offering = None
        if inst.bond_offerings:
            offering = sorted(inst.bond_offerings, key=lambda o: o.offering_date or date.min, reverse=True)[0]

        price_result = await db.execute(
            select(Price).where(Price.instrument_id == inst.id).order_by(Price.date.desc()).limit(1)
        )
        last_price_row = price_result.scalar_one_or_none()
        current_price = float(last_price_row.close) if last_price_row and last_price_row.close else 0

        if current_price == 0 and offering and offering.nominal_price:
            pct = offering.current_price_pct or 100.0
            current_price = offering.nominal_price * pct / 100.0

        qty = float(pos.quantity)
        avg_price = float(pos.avg_price or 0)
        pos_value = current_price * qty
        pos_invested = avg_price * qty if avg_price > 0 else pos_value
        profit = pos_value - pos_invested
        profit_pct = (profit / pos_invested * 100) if pos_invested > 0 else 0

        total_value += pos_value
        total_invested += pos_invested

        items.append({
            "id": str(inst.id),
            "ticker": inst.ticker,
            "isin": offering.isin if offering else (inst.isin or ""),
            "name": inst.full_name or inst.ticker,
            "issuer": inst.full_name or "",
            "quantity": qty,
            "avgPrice": round(avg_price, 2),
            "currentPrice": round(current_price, 2),
            "totalValue": round(pos_value, 2),
            "totalInvested": round(pos_invested, 2),
            "profit": round(profit, 2),
            "profitPercent": round(profit_pct, 2),
            "ytm": round(offering.yield_to_maturity, 2) if offering and offering.yield_to_maturity else 0,
            "couponYield": round(offering.coupon_rate, 2) if offering and offering.coupon_rate else 0,
            "duration": round(offering.duration_years, 2) if offering and offering.duration_years else 0,
            "rating": (offering.credit_rating or "NR") if offering else "NR",
            "maturityDate": offering.maturity_date.isoformat() if offering and offering.maturity_date else "",
            "aiScore": 50,
            "allocation": 0.0,
        })

    total_profit = total_value - total_invested
    total_return = (total_profit / total_invested * 100) if total_invested > 0 else 0

    ytms = [i["ytm"] for i in items if i["ytm"] > 0]
    avg_ytm = round(sum(ytms) / len(ytms), 2) if ytms else 0

    summary = {
        "totalValue": round(total_value, 2),
        "totalProfit": round(total_profit, 2),
        "totalReturn": round(total_return, 2),
        "avgYtm": avg_ytm,
        "avgAiScore": 50,
    }

    sorted_by_value = sorted(items, key=lambda x: x["totalValue"], reverse=True)
    for i in sorted_by_value:
        if total_value > 0:
            i["allocation"] = round(i["totalValue"] / total_value * 100, 1)

    allocation = {
        "recommended": [
            {"label": "ОФЗ", "value": 30},
            {"label": "Корпоративные AAA", "value": 25},
            {"label": "Корпоративные A", "value": 25},
            {"label": "Высокодоходные", "value": 10},
            {"label": "Кэш", "value": 10},
        ],
        "actual": [
            {"label": "ОФЗ", "value": 0},
            {"label": "Корпоративные AAA", "value": 0},
            {"label": "Корпоративные A", "value": 0},
            {"label": "Высокодоходные", "value": 0},
            {"label": "Кэш", "value": 0},
        ],
    }

    for i in sorted_by_value:
        label = "ОФЗ" if i["ticker"].startswith("SU") else "Корпоративные AAA" if i["rating"].startswith("A") else "Корпоративные A" if i["rating"].startswith("BBB") else "Высокодоходные"
        for a in allocation["actual"]:
            if a["label"] == label:
                a["value"] = round(a["value"] + (i.get("allocation", 0) or 0), 1)

    return {
        "positions": sorted_by_value,
        "summary": summary,
        "allocation": allocation,
    }
