"""Tests for position & sector compliance limits"""

from __future__ import annotations

from src.trading.compliance.limits import (
    check_overall_portfolio_limits,
    check_position_limit,
    check_short_eligibility,
)


def test_position_limit_within():
    result = check_position_limit(ticker="SBER", quantity=100, price=250, portfolio_value=1_000_000)
    assert result.passed is True
    assert len(result.blocks) == 0


def test_position_limit_exceeded():
    result = check_position_limit(ticker="SBER", quantity=1000, price=2500, portfolio_value=1_000_000)
    assert result.passed is False
    assert len(result.blocks) > 0
    assert "limit" in result.blocks[0]


def test_position_limit_zero_portfolio():
    result = check_position_limit(ticker="SBER", quantity=100, price=250, portfolio_value=0)
    assert result.passed is True
    assert len(result.warnings) > 0


def test_short_eligibility_insufficient_capital():
    result = check_short_eligibility(ticker="SBER", quantity=10, price=250, portfolio_value=10_000)
    assert result.passed is False
    assert "min for short" in result.blocks[0]


def test_short_eligibility_exceeds_limit():
    result = check_short_eligibility(ticker="SBER", quantity=100_000, price=250, portfolio_value=10_000_000)
    assert result.passed is False


def test_overall_portfolio_limits_normal():
    result = check_overall_portfolio_limits(portfolio_value=1_000_000, total_short_value=50_000, total_loan=0)
    assert result.passed is True


def test_overall_portfolio_limits_leverage_exceeded():
    result = check_overall_portfolio_limits(portfolio_value=1_000_000, total_short_value=0, total_loan=4_000_000)
    assert result.passed is False
    assert "Leverage" in result.blocks[0]


def test_overall_portfolio_limits_short_exceeded():
    result = check_overall_portfolio_limits(portfolio_value=1_000_000, total_short_value=500_000, total_loan=0)
    assert result.passed is False
