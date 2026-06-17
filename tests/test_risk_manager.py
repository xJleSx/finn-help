"""Tests for risk manager"""

from __future__ import annotations

import numpy as np
import pytest

from src.risk.manager import (
    compute_position_size,
    compute_stop_loss,
    compute_var,
    historical_var,
    kelly_fraction,
)


def test_historical_var():
    returns = np.array([-0.01, -0.02, -0.03, 0.01, 0.02, 0.03, -0.015, -0.025, -0.01, -0.005, 0.01, 0.015])
    var = historical_var(returns, 0.95)
    assert var > 0
    assert var < 0.05

    var = historical_var(np.array([]), 0.95)
    assert var == 0.0


def test_compute_var():
    prices = [100, 101, 102, 99, 98, 97, 100, 103, 104, 102, 101, 99]
    result = compute_var(prices, 0.95)
    assert "var_95" in result
    assert "var_99" in result
    assert "cvar_95" in result
    assert result["var_95"] >= 0

    result = compute_var([100], 0.95)
    assert result["var_95"] == 0.0


def test_kelly_fraction():
    kelly = kelly_fraction(win_rate=0.6, avg_win_pct=0.1, avg_loss_pct=0.05)
    b = 0.1 / 0.05
    expected = max(0.0, min((b * 0.6 - 0.4) / b, 0.25))
    assert kelly == expected

    kelly = kelly_fraction(win_rate=0.5, avg_win_pct=0.1, avg_loss_pct=0.1)
    assert kelly == 0.0

    kelly = kelly_fraction(win_rate=0.3, avg_win_pct=0.05, avg_loss_pct=0.1)
    assert kelly == 0.0


def test_kelly_fraction_clamp():
    kelly = kelly_fraction(win_rate=0.9, avg_win_pct=0.5, avg_loss_pct=0.05, max_kelly=0.25)
    assert kelly <= 0.25

    kelly = kelly_fraction(win_rate=0.5, avg_win_pct=0.1, avg_loss_pct=0.1, max_kelly=0.25)
    assert kelly >= 0


def test_compute_stop_loss_atr():
    result = compute_stop_loss(price=250.0, atr=15.0, multiplier=2.0)
    assert result is not None
    assert result["stop_loss"] == round(250.0 - 2.0 * 15.0, 2)
    assert result["stop_loss_pct"] == round(-(2.0 * 15.0 / 250.0) * 100, 2)


def test_compute_stop_loss_no_atr():
    result = compute_stop_loss(price=250.0, atr=0, multiplier=2.0)
    assert result is None


def test_compute_position_size():
    result = compute_position_size(
        capital=100000,
        price=250.0,
        risk_per_trade_pct=2.0,
        stop_loss_pct=5.0,
    )
    assert result["shares"] > 0
    assert result["amount"] > 0

    result_kelly = compute_position_size(
        capital=100000,
        price=250.0,
        stop_loss_pct=5.0,
        method="kelly",
        win_rate=0.55,
        avg_win_pct=0.08,
        avg_loss_pct=0.05,
    )
    assert result_kelly["shares"] > 0
    assert result_kelly["risk_amount"] > result["risk_amount"]


def test_compute_position_size_edge_cases():
    result = compute_position_size(
        capital=0,
        price=250.0,
        risk_per_trade_pct=2.0,
        stop_loss_pct=5.0,
    )
    assert result["shares"] == 0

    result = compute_position_size(
        capital=100000,
        price=0,
        risk_per_trade_pct=2.0,
        stop_loss_pct=5.0,
    )
    assert result["shares"] == 0

    result = compute_position_size(
        capital=100000,
        price=250.0,
        risk_per_trade_pct=2.0,
        stop_loss_pct=0,
    )
    assert result["shares"] > 0
