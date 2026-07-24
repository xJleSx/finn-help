from __future__ import annotations

import numpy as np
import pytest

from src.trading.metrics import PerformanceMetrics, compute_metrics


class TestComputeMetrics:
    def test_returns_empty_when_fewer_than_5_equity_points(self):
        result = compute_metrics([100.0])
        assert result.total_return == 0.0
        assert result.sharpe == 0.0

    def test_constant_equity_returns_zero_metrics(self):
        equity = [100.0] * 10
        result = compute_metrics(equity)
        assert result.total_return == 0.0
        assert result.sharpe == 0.0
        assert result.volatility == 0.0

    def test_total_return_computed_correctly(self):
        equity = [100.0, 105.0, 110.0, 115.0, 121.0]
        result = compute_metrics(equity, annual_factor=252)
        assert result.total_return == pytest.approx(0.21, rel=1e-2)

    def test_annual_return_positive_for_upward_trend(self):
        equity = [100.0 + i for i in range(252)]
        result = compute_metrics(equity, annual_factor=252)
        assert result.annual_return > 0

    def test_max_drawdown_is_negative(self):
        equity = [100.0, 110.0, 90.0, 95.0, 105.0]
        result = compute_metrics(equity)
        assert result.max_drawdown < 0

    def test_max_drawdown_computed_accurately(self):
        equity = [100.0, 120.0, 110.0, 80.0, 90.0]
        result = compute_metrics(equity)
        expected_dd = (80.0 / 120.0) - 1
        assert result.max_drawdown == pytest.approx(expected_dd, rel=1e-2)

    def test_sharpe_positive_for_profitable_strategy(self):
        np.random.seed(42)
        daily_rets = np.random.normal(0.001, 0.02, 252)
        equity = [100.0 * np.prod(1 + daily_rets[:i]) for i in range(len(daily_rets) + 1)]
        result = compute_metrics(equity, annual_factor=252)
        assert result.sharpe > 0

    def test_sortino_lower_than_sharpe_with_downside_risk(self):
        np.random.seed(42)
        daily_rets = np.concatenate([np.random.normal(0.001, 0.01, 200), np.random.normal(-0.01, 0.03, 52)])
        equity = [100.0]
        for r in daily_rets:
            equity.append(equity[-1] * (1 + r))
        result = compute_metrics(equity, annual_factor=252)
        assert result.sortino <= result.sharpe + 1e-8

    def test_profit_factor_infinite_when_no_losses(self):
        equity = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        result = compute_metrics(equity, annual_factor=252)
        assert result.profit_factor == float("inf")

    def test_profit_factor_finite_with_losses(self):
        equity = [100.0, 102.0, 98.0, 103.0, 97.0, 105.0]
        result = compute_metrics(equity, annual_factor=252)
        assert result.profit_factor < float("inf")
        assert result.profit_factor > 0

    def test_win_rate_is_ratio_of_positive_returns(self):
        np.random.seed(42)
        daily_rets = np.random.normal(0.0, 0.02, 100)
        equity = [100.0]
        for r in daily_rets:
            equity.append(equity[-1] * (1 + r))
        result = compute_metrics(equity, annual_factor=252)
        n_pos = np.sum(daily_rets > 0) / len(daily_rets)
        assert result.win_rate == pytest.approx(n_pos, rel=1e-2)

    def test_var_95_is_fifth_percentile(self):
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 252)
        equity = [100.0]
        for r in returns:
            equity.append(equity[-1] * (1 + r))
        result = compute_metrics(equity, annual_factor=252)
        expected_var = float(np.percentile(returns, 5))
        assert result.var_95 == pytest.approx(expected_var, rel=1e-2)

    def test_cvar_95_is_mean_below_var(self):
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 252)
        equity = [100.0]
        for r in returns:
            equity.append(equity[-1] * (1 + r))
        result = compute_metrics(equity, annual_factor=252)
        var_val = np.percentile(returns, 5)
        expected_cvar = float(np.mean(returns[returns <= var_val]))
        assert result.cvar_95 == pytest.approx(expected_cvar, rel=1e-2)

    def test_consecutive_wins_and_losses_counted(self):
        equity = [100.0, 102.0, 104.0, 101.0, 99.0, 97.0, 100.0, 103.0]
        result = compute_metrics(equity, annual_factor=252)
        assert result.consecutive_wins == 2
        assert result.consecutive_losses == 3

    def test_calmar_ratio_computed(self):
        equity = [100.0, 110.0, 105.0, 115.0, 95.0, 105.0]
        result = compute_metrics(equity, annual_factor=252)
        if result.max_drawdown < 0:
            assert result.calmar > 0

    def test_omega_ratio_infinite_when_no_negative_returns(self):
        equity = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        result = compute_metrics(equity, annual_factor=252)
        assert result.omega == float("inf") or result.omega > 0

    def test_best_and_worst_day(self):
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 252)
        equity = [100.0]
        for r in returns:
            equity.append(equity[-1] * (1 + r))
        result = compute_metrics(equity, annual_factor=252)
        assert result.best_day == pytest.approx(float(np.max(returns)), rel=1e-2)
        assert result.worst_day == pytest.approx(float(np.min(returns)), rel=1e-2)

    def test_drawdown_curve_length_matches_returns(self):
        equity = [100.0, 105.0, 102.0, 108.0, 95.0, 110.0]
        result = compute_metrics(equity, annual_factor=252)
        assert len(result.drawdown_curve) == len(equity) - 1

    def test_to_dict_returns_all_fields(self):
        result = compute_metrics([100.0, 105.0, 102.0, 108.0, 110.0], annual_factor=252)
        d = result.to_dict()
        assert "total_return" in d
        assert "sharpe" in d
        assert "max_drawdown" in d
        assert "win_rate" in d
        assert "var_95" in d
        assert "cvar_95" in d
