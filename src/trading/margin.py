from __future__ import annotations

import logging
from typing import Any

from src.config import settings
from src.trading.types import LeverageInfo, MarginRequirements

logger = logging.getLogger(__name__)


def _init_margin_pct() -> float:
    return getattr(settings, "margin_initial_pct", 0.25)


def _maintenance_margin_pct() -> float:
    return getattr(settings, "margin_maintenance_pct", 0.15)


def _short_init_margin_pct() -> float:
    return getattr(settings, "short_initial_margin_pct", 0.50)


def _short_maintenance_margin_pct() -> float:
    return getattr(settings, "short_maintenance_margin_pct", 0.30)


def _max_leverage() -> float:
    return getattr(settings, "max_leverage", 3.0)


def compute_margin_requirements(
    position_value: float,
    is_short: bool = False,
    portfolio_value: float = 0.0,
    existing_loan: float = 0.0,
    avg_entry_price: float = 0.0,
) -> MarginRequirements:
    req = MarginRequirements()
    if is_short:
        req.initial_margin = position_value * _short_init_margin_pct()
        req.maintenance_margin = position_value * _short_maintenance_margin_pct()
    else:
        req.initial_margin = position_value * _init_margin_pct()
        req.maintenance_margin = position_value * _maintenance_margin_pct()
    total_value = portfolio_value if portfolio_value > 0 else position_value
    borrowed = existing_loan
    req.loan_amount = borrowed
    req.portfolio_value = total_value
    equity = total_value - borrowed
    req.leverage = total_value / equity if equity > 0 else float("inf")
    if total_value > 0 and equity > 0:
        margin_deficit = borrowed + req.initial_margin - total_value
        req.free_cash = max(0.0, equity - req.initial_margin)
        req.margin_used_pct = req.initial_margin / equity if equity > 0 else 1.0
        if is_short and avg_entry_price > 0:
            quantity = position_value / avg_entry_price
            req.margin_call_price = avg_entry_price * (1 + _short_maintenance_margin_pct())
            req.liquidation_price = avg_entry_price * (1 + _short_init_margin_pct())
        elif margin_deficit > 0 and avg_entry_price > 0:
            quantity = position_value / avg_entry_price
            loan_per_share = borrowed / quantity if quantity > 0 else 0
            req.margin_call_price = loan_per_share / (1 - _init_margin_pct())
            req.liquidation_price = loan_per_share / (1 - _maintenance_margin_pct())
        else:
            req.margin_call_price = 0
            req.liquidation_price = 0
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
    req.portfolio_value = cash_balance + gross_long
    long_margin = gross_long * _init_margin_pct()
    short_margin = gross_short * _short_init_margin_pct()
    req.initial_margin = long_margin + short_margin
    long_maintenance = gross_long * _maintenance_margin_pct()
    short_maintenance = gross_short * _short_maintenance_margin_pct()
    req.maintenance_margin = long_maintenance + short_maintenance
    borrowed_for_long = max(0.0, gross_long - cash_balance)
    short_liability = gross_short
    req.loan_amount = borrowed_for_long + short_liability
    equity = req.portfolio_value - req.loan_amount
    if req.portfolio_value > 0:
        req.leverage = req.portfolio_value / equity if equity > 0 else float("inf")
    req.free_cash = max(0.0, equity - req.initial_margin)
    req.margin_used_pct = req.initial_margin / equity if equity > 0 else 0
    if equity <= 0:
        req.margin_status = "liquidation"
    elif equity < req.maintenance_margin:
        req.margin_status = "margin_call"
    elif equity < req.initial_margin:
        req.margin_status = "warning"
    else:
        req.margin_status = "safe"
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
    info.margin_call_level = portfolio_value * (1 - 1 / (_max_leverage() * 0.8))
    info.liquidation_level = portfolio_value * (1 - 1 / _max_leverage())
    max_lev = _max_leverage()
    if info.leverage_ratio >= max_lev:
        info.margin_status = "liquidation"
    elif info.leverage_ratio >= max_lev * 0.8:
        info.margin_status = "margin_call"
    elif info.leverage_ratio >= max_lev * 0.6:
        info.margin_status = "warning"
    else:
        info.margin_status = "safe"
    return info


def compute_borrow_cost(
    position_value: float,
    borrow_rate: float,
    days_held: int,
) -> float:
    return position_value * borrow_rate * (days_held / 365)


def compute_interest(
    loan_amount: float,
    annual_rate: float = 0.18,
    days: int = 1,
) -> float:
    return loan_amount * (annual_rate / 365) * days
