from __future__ import annotations

import logging
from typing import Any

from src.trading.types import LeverageInfo, MarginRequirements

logger = logging.getLogger(__name__)

INITIAL_MARGIN_PCT: float = 0.25
MAINTENANCE_MARGIN_PCT: float = 0.15
MARGIN_CALL_PCT: float = 0.20
LIQUIDATION_PCT: float = 0.10
SHORT_INITIAL_MARGIN_PCT: float = 0.50
SHORT_MAINTENANCE_MARGIN_PCT: float = 0.30
BROKER_INTEREST_RATE_ANNUAL: float = 0.18
MAX_LEVERAGE: float = 3.0


def compute_margin_requirements(
    position_value: float,
    is_short: bool = False,
    portfolio_value: float = 0.0,
    existing_loan: float = 0.0,
) -> MarginRequirements:
    req = MarginRequirements()
    if is_short:
        req.initial_margin = position_value * SHORT_INITIAL_MARGIN_PCT
        req.maintenance_margin = position_value * SHORT_MAINTENANCE_MARGIN_PCT
    else:
        req.initial_margin = position_value * INITIAL_MARGIN_PCT
        req.maintenance_margin = position_value * MAINTENANCE_MARGIN_PCT
    total_value = portfolio_value + position_value if portfolio_value > 0 else position_value
    borrowed = existing_loan
    req.loan_amount = borrowed
    req.portfolio_value = total_value
    equity = total_value - borrowed
    req.leverage = total_value / equity if equity > 0 else float("inf")
    if total_value > 0 and equity > 0:
        margin_deficit = borrowed + req.initial_margin - total_value
        req.free_cash = max(0.0, equity - req.initial_margin)
        req.margin_used_pct = req.initial_margin / equity if equity > 0 else 1.0
        if margin_deficit > 0:
            if is_short:
                price_per_share = position_value / 1
                req.margin_call_price = price_per_share * (1 + SHORT_MAINTENANCE_MARGIN_PCT) + (borrowed / 1)
            else:
                req.margin_call_price = position_value * (1 - MARGIN_CALL_PCT)
            req.liquidation_price = position_value * (1 - LIQUIDATION_PCT)
    return req


def compute_portfolio_margin(
    long_positions: list[dict[str, Any]],
    short_positions: list[dict[str, Any]],
    cash_balance: float,
    current_prices: dict[str, float],
) -> MarginRequirements:
    req = MarginRequirements()
    gross_long = sum(p["quantity"] * current_prices.get(p["ticker"], p.get("avg_price", 0)) for p in long_positions)
    gross_short = sum(p["quantity"] * current_prices.get(p["ticker"], p.get("avg_price", 0)) for p in short_positions)
    req.portfolio_value = cash_balance + gross_long - gross_short
    long_margin = gross_long * INITIAL_MARGIN_PCT
    short_margin = gross_short * SHORT_INITIAL_MARGIN_PCT
    req.initial_margin = long_margin + short_margin
    long_maintenance = gross_long * MAINTENANCE_MARGIN_PCT
    short_maintenance = gross_short * SHORT_MAINTENANCE_MARGIN_PCT
    req.maintenance_margin = long_maintenance + short_maintenance
    req.loan_amount = max(0.0, gross_long + req.initial_margin - cash_balance)
    if req.portfolio_value > 0:
        equity = req.portfolio_value - req.loan_amount
        req.leverage = req.portfolio_value / equity if equity > 0 else float("inf")
    req.free_cash = max(0.0, cash_balance - req.loan_amount - req.maintenance_margin)
    req.margin_used_pct = (req.initial_margin + req.loan_amount) / req.portfolio_value if req.portfolio_value > 0 else 0
    equity = req.portfolio_value - req.loan_amount
    if equity < req.maintenance_margin:
        req.margin_status = "margin_call"
    elif equity < req.initial_margin:
        req.margin_status = "warning"
    else:
        req.margin_status = "safe"
    if equity <= 0 and req.loan_amount > 0:
        req.margin_status = "liquidation"
    return req


def compute_leverage_info(
    portfolio_value: float,
    total_loan: float,
    cash_balance: float,
    margin_used: float,
) -> LeverageInfo:
    info = LeverageInfo()
    info.portfolio_value = portfolio_value
    info.total_loan = total_loan
    equity = portfolio_value - total_loan
    info.leverage_ratio = portfolio_value / equity if equity > 0 else float("inf")
    info.used_margin = margin_used
    info.free_margin = max(0.0, cash_balance - margin_used)
    info.margin_call_level = portfolio_value * MARGIN_CALL_PCT
    info.liquidation_level = portfolio_value * LIQUIDATION_PCT
    if info.leverage_ratio > MAX_LEVERAGE:
        info.margin_status = "liquidation"
    elif info.leverage_ratio > MAX_LEVERAGE * 0.8:
        info.margin_status = "margin_call"
    elif info.leverage_ratio > MAX_LEVERAGE * 0.6:
        info.margin_status = "warning"
    else:
        info.margin_status = "safe"
    return info


def compute_borrow_cost(
    position_value: float,
    borrow_rate: float,
    days_held: int,
) -> float:
    return position_value * (borrow_rate / 100) * (days_held / 365)


def compute_interest(
    loan_amount: float,
    annual_rate: float = BROKER_INTEREST_RATE_ANNUAL,
    days: int = 1,
) -> float:
    return loan_amount * (annual_rate / 365) * days
