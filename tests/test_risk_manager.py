"""Tests for risk manager"""

from __future__ import annotations

import numpy as np
import pytest

from src.trading.risk.manager import (
    compute_concentration_limit,
    compute_position_size,
    compute_risk_score,
    compute_stop_loss,
    compute_var,
    historical_var,
    kelly_fraction,
)


class TestHistoricalVar:
    def test_empty_returns_zero(self):
        assert historical_var(np.array([])) == 0.0

    def test_short_series_returns_zero(self):
        assert historical_var(np.array([1, 2, 3, 4, 5])) == 0.0

    def test_returns_positive(self):
        arr = np.random.default_rng(42).normal(0, 0.02, 100)
        result = historical_var(arr)
        assert result > 0


class TestComputeVar:
    def test_short_series(self):
        result = compute_var([100.0, 101.0])
        assert result == {"var_95": 0.0, "var_99": 0.0, "cvar_95": 0.0}

    def test_returns_expected_keys(self):
        prices = [100.0 + i + np.random.default_rng(42).normal(0, 2) for i in range(60)]
        result = compute_var(prices)
        assert "var_95" in result
        assert "var_99" in result
        assert "cvar_95" in result
        assert result["var_95"] >= 0
        assert result["cvar_95"] >= result["var_95"]

    def test_all_positive_prices(self):
        prices = [50.0 + i * 0.1 for i in range(30)]
        result = compute_var(prices)
        for v in result.values():
            assert v >= 0


class TestComputeStopLoss:
    def test_none_atr(self):
        assert compute_stop_loss(price=100.0, atr=None) is None

    def test_zero_atr(self):
        assert compute_stop_loss(price=100.0, atr=0.0) is None

    def test_zero_price(self):
        assert compute_stop_loss(price=0.0, atr=5.0) is None

    def test_negative_price(self):
        assert compute_stop_loss(price=-10.0, atr=5.0) is None

    def test_normal_case(self):
        result = compute_stop_loss(price=100.0, atr=5.0, multiplier=2.0)
        assert result is not None
        assert result["stop_loss"] == 90.0
        assert result["stop_loss_pct"] == -10.0
        assert result["atr_multiple"] == 2.0

    def test_custom_multiplier(self):
        result = compute_stop_loss(price=200.0, atr=10.0, multiplier=3.0)
        assert result is not None
        assert result["stop_loss"] == 170.0
        assert result["stop_loss_pct"] == -15.0

    def test_large_atr(self):
        result = compute_stop_loss(price=50.0, atr=25.0, multiplier=2.0)
        assert result is not None
        assert result["stop_loss"] == 0.0
        assert result["stop_loss_pct"] == -100.0


class TestComputeConcentrationLimit:
    def test_zero_price(self):
        result = compute_concentration_limit(capital=1_000_000, price=0.0)
        assert result == {"shares": 0, "amount": 0.0, "max_pct": 20.0}

    def test_negative_price(self):
        result = compute_concentration_limit(capital=1_000_000, price=-50.0)
        assert result == {"shares": 0, "amount": 0.0, "max_pct": 20.0}

    def test_normal_case(self):
        result = compute_concentration_limit(capital=1_000_000, price=250.0)
        assert result["shares"] == 800
        assert result["amount"] == 200_000.0
        assert result["max_pct"] == 20.0

    def test_custom_max_pct(self):
        result = compute_concentration_limit(capital=100_000, price=50.0, max_position_pct=10.0)
        assert result["shares"] == 200
        assert result["amount"] == 10_000.0
        assert result["max_pct"] == 10.0

    def test_zero_capital(self):
        result = compute_concentration_limit(capital=0, price=100.0)
        assert result == {"shares": 0, "amount": 0.0, "max_pct": 20.0}


class TestComputeRiskScore:
    def test_zero_risk(self):
        score = compute_risk_score(var_95=0.0, stop_loss_pct=-1.0)
        assert 0 <= score <= 1

    def test_max_risk(self):
        score = compute_risk_score(var_95=25.0, stop_loss_pct=-25.0, atr_ratio=10.0)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_mid_risk(self):
        score = compute_risk_score(var_95=5.0, stop_loss_pct=-5.0, atr_ratio=3.0)
        assert 0 < score < 1

    def test_without_atr(self):
        score = compute_risk_score(var_95=3.0, stop_loss_pct=-3.0)
        assert 0 < score < 1

    def test_atr_none(self):
        score = compute_risk_score(var_95=3.0, stop_loss_pct=-3.0, atr_ratio=None)
        assert 0 < score < 1


class TestKellyFraction:
    def test_no_win_rate(self):
        assert kelly_fraction(win_rate=0.0, avg_win_pct=10.0, avg_loss_pct=5.0) == 0.0

    def test_negative_avg_loss(self):
        assert kelly_fraction(win_rate=0.6, avg_win_pct=10.0, avg_loss_pct=0.0) == 0.0

    def test_zero_b_ratio(self):
        assert kelly_fraction(win_rate=0.5, avg_win_pct=0.0, avg_loss_pct=5.0) == 0.0

    def test_perfect_odds(self):
        fraction = kelly_fraction(win_rate=1.0, avg_win_pct=10.0, avg_loss_pct=5.0)
        assert fraction == 0.25  # capped by max_kelly

    def test_capped_at_max(self):
        fraction = kelly_fraction(win_rate=1.0, avg_win_pct=100.0, avg_loss_pct=1.0)
        assert fraction == 0.25

    def test_typical_case(self):
        fraction = kelly_fraction(win_rate=0.55, avg_win_pct=20.0, avg_loss_pct=10.0)
        assert 0 < fraction <= 0.25

    def test_custom_max_kelly(self):
        fraction = kelly_fraction(win_rate=1.0, avg_win_pct=10.0, avg_loss_pct=5.0, max_kelly=0.5)
        assert fraction == 0.5


class TestComputePositionSize:
    def test_zero_price(self):
        result = compute_position_size(capital=100_000, price=0.0)
        assert result == {"shares": 0, "amount": 0.0, "risk_amount": 0.0}

    def test_fixed_fractional_default(self):
        result = compute_position_size(capital=100_000, price=250.0)
        assert result["shares"] > 0
        assert result["amount"] > 0
        assert result["risk_amount"] == 2_000.0
        assert result["method"] == "fixed_fractional"

    def test_kelly_method(self):
        result = compute_position_size(
            capital=100_000,
            price=250.0,
            method="kelly",
            win_rate=0.6,
            avg_win_pct=20.0,
            avg_loss_pct=10.0,
        )
        assert result["shares"] > 0
        assert result["method"] == "kelly"

    def test_with_stop_loss(self):
        result = compute_position_size(capital=100_000, price=250.0, stop_loss_pct=-5.0)
        assert result["shares"] > 0

    def test_zero_risk_per_trade(self):
        result = compute_position_size(capital=100_000, price=250.0, risk_per_trade_pct=0.0)
        assert result["shares"] == 0
        assert result["amount"] == 0.0
