from __future__ import annotations

import numpy as np
import pytest

from src.analysis.backtest import (
    BacktestConfig,
    BacktestResult,
    MonteCarloResult,
    RegimeInfo,
    _max_drawdown,
    _returns,
    _sharpe,
    _sortino,
    apply_costs,
    detect_regime,
    run_monte_carlo,
)


class TestBacktestHelpers:
    def test_returns_empty(self):
        assert len(_returns([])) == 0

    def test_returns_single(self):
        assert len(_returns([100])) == 0

    def test_returns_correct(self):
        r = _returns([100, 110, 121])
        np.testing.assert_almost_equal(r, [0.1, 0.1])

    def test_sharpe_zero_std(self):
        assert _sharpe(np.array([0.01])) == 0.0

    def test_sharpe_normal(self):
        rng = np.random.default_rng(42)
        r = rng.normal(0.001, 0.02, 252)
        s = _sharpe(r)
        assert s > 0

    def test_max_drawdown_zero(self):
        assert _max_drawdown([100]) == 0.0

    def test_max_drawdown_known(self):
        dd = _max_drawdown([100, 110, 90, 80, 105])
        assert round(dd, 2) == -0.27

    def test_sortino_no_downside(self):
        assert _sortino(np.array([0.01, 0.02])) == 0.0

    def test_sortino_normal(self):
        rng = np.random.default_rng(99)
        r = rng.normal(0.001, 0.02, 252)
        s = _sortino(r)
        assert isinstance(s, float)


class TestBacktestResult:
    def test_empty_result(self):
        r = BacktestResult(capital=100000)
        assert r.portfolio_return == 0.0
        assert r.benchmark_return == 0.0
        assert r.portfolio_sharpe == 0.0
        assert r.portfolio_max_dd == 0.0

    def test_single_snapshot(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("2025-01-01", 0.01, 0.005)
        assert len(r.dates) == 1
        assert r.portfolio_return == pytest.approx(0.01, rel=1e-6)

    def test_cumulative_return(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.1, 0.05)
        r.add_snapshot("d2", 0.1, 0.05)
        assert round(r.portfolio_return, 4) == 0.21

    def test_alpha_positive(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.1, 0.02)
        assert r.alpha == pytest.approx(0.08, rel=1e-6)

    def test_win_rate(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.01, 0)
        r.add_snapshot("d2", -0.01, 0)
        r.add_snapshot("d3", 0.02, 0)
        assert r.win_rate == 2 / 3

    def test_profit_factor(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.05, 0)
        r.add_snapshot("d2", -0.02, 0)
        assert r.profit_factor == 0.05 / 0.02

    def test_profit_factor_infinite(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.05, 0)
        assert r.profit_factor == float("inf")

    def test_avg_win_loss(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.05, 0)
        r.add_snapshot("d2", -0.03, 0)
        r.add_snapshot("d3", 0.01, 0)
        assert r.avg_win == pytest.approx(0.03, rel=1e-3)
        assert r.avg_loss == pytest.approx(-0.03, rel=1e-3)

    def test_summary_contains_metrics(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.01, 0.005)
        summary = r.summary()
        assert "100,000" in summary
        assert "Sharpe" in summary
        assert "Sortino" in summary
        assert "Calmar" in summary

    def test_summary_with_monte_carlo(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.01, 0.005)
        r.monte_carlo = MonteCarloResult(
            simulations=100,
            mean_return=0.1,
            std_return=0.2,
            var_95=-0.25,
            cvar_95=-0.35,
            upside_pct=0.65,
            downside_pct=0.35,
            best_return=0.5,
            worst_return=-0.4,
            median_return=0.12,
        )
        summary = r.summary()
        assert "Monte-Carlo" in summary
        assert "VaR" in summary
        assert "CVaR" in summary

    def test_summary_with_regime(self):
        r = BacktestResult(capital=100000)
        r.add_snapshot("d1", 0.01, 0.005)
        r.regime = RegimeInfo(regime="BULL", volatility=0.15, trend_strength=0.8, avg_return=0.02)
        summary = r.summary()
        assert "BULL" in summary


class TestApplyCosts:
    def test_no_rebalance_no_costs(self):
        net, slip, comm = apply_costs(0.01, is_rebalance=False, position_weight=0.25, config=BacktestConfig())
        assert slip == 0.0
        assert comm == 0.0
        assert net == 0.01

    def test_rebalance_applies_slippage(self):
        config = BacktestConfig(slippage_bps=10)
        net, slip, comm = apply_costs(0.01, is_rebalance=True, position_weight=0.5, config=config)
        assert slip > 0

    def test_rebalance_applies_commission(self):
        config = BacktestConfig(commission_pct=0.001)
        net, slip, comm = apply_costs(0.01, is_rebalance=True, position_weight=0.5, config=config)
        assert comm > 0


class TestMonteCarlo:
    def test_no_data_returns_zero(self):
        mc = run_monte_carlo([], n_simulations=100, periods=50)
        assert mc.simulations == 0
        assert mc.mean_return == 0.0

    def test_short_data_returns_zero(self):
        mc = run_monte_carlo([0.01] * 5, n_simulations=50, periods=20)
        assert mc.simulations == 0

    def test_returns_monte_carlo_result(self):
        returns = np.random.default_rng(42).normal(0.001, 0.02, 252).tolist()
        mc = run_monte_carlo(returns, n_simulations=200, periods=252)
        assert mc.simulations == 200
        assert -0.5 < mc.var_95 < 0
        assert -0.5 < mc.cvar_95 < 0
        assert 0.0 < mc.upside_pct < 1.0
        assert mc.best_return > mc.worst_return
        assert mc.median_return is not None

    def test_upside_and_downside_sum(self):
        returns = np.random.default_rng(7).normal(0.0, 0.02, 252).tolist()
        mc = run_monte_carlo(returns, n_simulations=100, periods=252)
        total = mc.upside_pct + mc.downside_pct
        assert total == pytest.approx(1.0, abs=0.02) or mc.upside_pct == 0.0


class TestRegimeDetection:
    def test_unknown_for_short_data(self):
        regime = detect_regime(np.array([0.01] * 5), lookback=21)
        assert regime.regime == "UNKNOWN"

    def test_bull_regime(self):
        returns = np.random.default_rng(1).normal(0.002, 0.015, 252)
        regime = detect_regime(returns, lookback=21)
        assert regime.regime in ("BULL", "SIDEWAYS", "HIGH_VOL")

    def test_regime_returns_expected_shape(self):
        returns = np.random.default_rng(5).normal(0.0, 0.02, 252)
        regime = detect_regime(returns, lookback=21)
        assert isinstance(regime, RegimeInfo)
        assert regime.volatility >= 0
        assert isinstance(regime.trend_strength, float)
        assert isinstance(regime.avg_return, float)


class TestBacktestConfig:
    def test_defaults(self):
        config = BacktestConfig()
        assert config.capital == 100_000
        assert config.lookback_days == 365
        assert config.slippage_bps == 5
        assert config.commission_pct == 0.0004

    def test_custom_values(self):
        config = BacktestConfig(capital=50000, slippage_bps=10, commission_pct=0.001)
        assert config.capital == 50000
        assert config.slippage_bps == 10
        assert config.commission_pct == 0.001
