"""Tests for margin & leverage calculations"""

from __future__ import annotations

from src.trading.margin import (
    compute_borrow_cost,
    compute_interest,
    compute_leverage_info,
    compute_margin_requirements,
    compute_portfolio_margin,
)


def test_compute_margin_requirements_long():
    req = compute_margin_requirements(position_value=100_000, is_short=False, portfolio_value=500_000)
    assert req.initial_margin == 25_000
    assert req.maintenance_margin == 15_000
    assert req.leverage > 0


def test_compute_margin_requirements_short():
    req = compute_margin_requirements(position_value=100_000, is_short=True, portfolio_value=500_000)
    assert req.initial_margin == 50_000
    assert req.maintenance_margin == 30_000


def test_compute_portfolio_margin_empty():
    req = compute_portfolio_margin(long_positions=[], short_positions=[], cash_balance=1_000_000, current_prices={})
    assert req.portfolio_value == 1_000_000
    assert req.margin_status == "safe"


def test_compute_portfolio_margin_with_short():
    req = compute_portfolio_margin(
        long_positions=[{"ticker": "SBER", "quantity": 100, "avg_price": 250}],
        short_positions=[{"ticker": "GAZP", "quantity": 50, "avg_price": 150}],
        cash_balance=1_000_000,
        current_prices={"SBER": 260, "GAZP": 145},
    )
    assert req.portfolio_value > 0
    assert req.initial_margin > 0


def test_compute_leverage_info_safe():
    info = compute_leverage_info(portfolio_value=1_000_000, total_loan=0, cash_balance=500_000, margin_used=100_000)
    assert info.leverage_ratio == 1.0
    assert info.margin_status == "safe"
    assert info.free_margin == 400_000


def test_compute_leverage_info_warning():
    info = compute_leverage_info(portfolio_value=1_000_000, total_loan=1_200_000, cash_balance=0, margin_used=900_000)
    assert info.leverage_ratio == float("inf")
    assert info.margin_status in ("margin_call", "warning", "liquidation")


def test_compute_leverage_info_liquidation():
    info = compute_leverage_info(portfolio_value=1_000_000, total_loan=3_500_000, cash_balance=0, margin_used=3_000_000)
    assert info.leverage_ratio > 3.0
    assert info.margin_status == "liquidation"


def test_borrow_cost():
    cost = compute_borrow_cost(position_value=100_000, borrow_rate=0.15, days_held=30)
    assert cost > 0
    assert cost == 100_000 * 0.15 * (30 / 365)


def test_compute_interest():
    interest = compute_interest(loan_amount=1_000_000, annual_rate=0.18, days=30)
    assert interest == 1_000_000 * (0.18 / 365) * 30


def test_margin_requirements_zero():
    req = compute_margin_requirements(position_value=0, portfolio_value=0)
    assert req.initial_margin == 0
    assert req.leverage == float("inf")
