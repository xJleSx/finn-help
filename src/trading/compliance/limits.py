from __future__ import annotations

import logging

from src.config import personal
from src.constants import SECTOR_LIMITS
from src.db.connection import get_session
from src.db.models import Portfolio
from src.trading.types import ComplianceCheck

logger = logging.getLogger(__name__)

POSITION_LIMIT_PCT: float = 0.25
SECTOR_LIMIT_PCT: float = 0.40
MAX_LEVERAGE: float = 3.0
MAX_SHORT_PCT: float = 0.20
MIN_CAPITAL_FOR_SHORT: float = 500_000


def check_position_limit(
    ticker: str,
    quantity: int,
    price: float,
    portfolio_value: float,
) -> ComplianceCheck:
    check = ComplianceCheck()
    if portfolio_value <= 0:
        check.warnings.append("Portfolio value is zero, cannot compute position limits")
        return check
    position_value = quantity * price
    position_pct = position_value / portfolio_value
    limit = float(personal.get("max_position_pct", POSITION_LIMIT_PCT))
    check.checks.append(
        {
            "check": "position_limit",
            "value_pct": position_pct,
            "limit_pct": limit,
        }
    )
    if position_pct > limit:
        check.blocks.append(f"Position {position_pct:.1%} > limit {limit:.1%}")
        check.passed = False
    elif position_pct > limit * 0.8:
        check.warnings.append(f"Near position limit: {position_pct:.1%}/{limit:.1%}")
    return check


def check_sector_limit(ticker: str, sector: str, position_value: float, portfolio_value: float) -> ComplianceCheck:
    check = ComplianceCheck()
    if portfolio_value <= 0:
        return check
    db = get_session()
    try:
        from sqlalchemy import func
        from src.db.models import Instrument, Price

        latest_price = (
            db.query(
                Price.instrument_id,
                Price.close,
                func.row_number()
                .over(partition_by=Price.instrument_id, order_by=Price.date.desc())
                .label("rn"),
            )
            .subquery()
        )
        sector_value = (
            db.query(func.coalesce(func.sum(Portfolio.quantity * latest_price.c.close), 0))
            .join(Instrument, Portfolio.instrument_id == Instrument.id)
            .join(
                latest_price,
                (latest_price.c.instrument_id == Instrument.id)
                & (latest_price.c.rn == 1),
            )
            .filter(Instrument.sector == sector)
            .scalar()
        ) or 0.0
        current_sector_value = float(sector_value)
        new_sector_value = current_sector_value + position_value
        sector_pct = new_sector_value / portfolio_value
        sector_limit = SECTOR_LIMITS.get(sector, SECTOR_LIMIT_PCT)
        check.checks.append(
            {
                "check": "sector_limit",
                "sector": sector,
                "value_pct": sector_pct,
                "limit_pct": sector_limit,
            }
        )
        if sector_pct > sector_limit:
            check.blocks.append(f"Sector {sector} {sector_pct:.1%} > limit {sector_limit:.1%}")
            check.passed = False
        elif sector_pct > sector_limit * 0.85:
            check.warnings.append(f"Near sector limit {sector}: {sector_pct:.1%}/{sector_limit:.1%}")
    finally:
        db.close()
    return check


def check_short_eligibility(ticker: str, quantity: int, price: float, portfolio_value: float) -> ComplianceCheck:
    check = ComplianceCheck()
    if portfolio_value < MIN_CAPITAL_FOR_SHORT:
        check.blocks.append(f"Capital {portfolio_value:,.0f} < min for short {MIN_CAPITAL_FOR_SHORT:,.0f}")
        check.passed = False
        return check
    short_value = quantity * price
    short_pct = short_value / portfolio_value
    limit = float(personal.get("max_short_pct", MAX_SHORT_PCT))
    check.checks.append(
        {
            "check": "short_limit",
            "value_pct": short_pct,
            "limit_pct": limit,
        }
    )
    if short_pct > limit:
        check.blocks.append(f"Short {short_pct:.1%} > limit {limit:.1%}")
        check.passed = False
    db = get_session()
    try:
        from src.db.models import Instrument

        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if inst and inst.instrument_type not in ("stock", "etf"):
            check.blocks.append(f"Short not allowed for {inst.instrument_type}")
            check.passed = False
    finally:
        db.close()
    return check


def check_overall_portfolio_limits(portfolio_value: float, total_short_value: float, total_loan: float) -> ComplianceCheck:
    check = ComplianceCheck()
    if portfolio_value <= 0:
        return check
    leverage = (portfolio_value + total_loan) / portfolio_value if portfolio_value > 0 else 1.0
    check.checks.append(
        {
            "check": "leverage_limit",
            "leverage": leverage,
            "max_leverage": MAX_LEVERAGE,
        }
    )
    if leverage > MAX_LEVERAGE:
        check.blocks.append(f"Leverage {leverage:.1f}x > max {MAX_LEVERAGE:.1f}x")
        check.passed = False
    short_pct = total_short_value / portfolio_value if portfolio_value > 0 else 0
    check.checks.append(
        {
            "check": "total_short_limit",
            "short_pct": short_pct,
            "limit": MAX_SHORT_PCT,
        }
    )
    if short_pct > MAX_SHORT_PCT:
        check.blocks.append(f"Total short {short_pct:.1%} > limit {MAX_SHORT_PCT:.1%}")
        check.passed = False
    return check
