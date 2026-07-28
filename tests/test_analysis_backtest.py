from __future__ import annotations

import numpy as np
import pytest

from src.analysis.backtest import (
    BacktestConfig,
    BacktestResult,
    apply_costs,
    detect_regime,
    run_monte_carlo,
)


class TestBacktestConfig:
    def test_defaults(self):
        cfg = BacktestConfig()
        assert cfg.capital == 100_000
        assert cfg.lookback_days == 365
        assert cfg.slippage_bps == 5

    def test_custom_values(self):
        cfg = BacktestConfig(capital=50_000, lookback_days=180)
        assert cfg.capital == 50_000
        assert cfg.lookback_days == 180


class TestBacktestResult:
    def test_empty_result(self):
        r = BacktestResult(capital=100_000)
        assert r.portfolio_return == 0.0
        assert r.benchmark_return == 0.0
        assert r.alpha == 0.0
        assert r.win_rate == 0.0
        assert r.avg_win == 0.0
        assert r.avg_loss == 0.0

    def test_with_returns(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("2024-01-01", 0.01, 0.005)
        r.add_snapshot("2024-01-02", -0.02, -0.01)
        r.add_snapshot("2024-01-03", 0.03, 0.02)
        assert len(r.dates) == 3
        assert r.win_rate == 2 / 3
        assert r.avg_win > 0
        assert r.avg_loss < 0

    def test_metrics_with_single_return(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("2024-01-01", 0.01, 0.005)
        assert r.portfolio_return == pytest.approx(0.01)
        assert r.alpha == pytest.approx(0.005)

    def test_summary_with_data(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("2024-01-01", 0.01, 0.005)
        r.add_snapshot("2024-01-02", 0.02, 0.01)
        assert isinstance(r.summary(), str)

    def test_profit_factor_all_wins(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("2024-01-01", 0.01, 0.0)
        r.add_snapshot("2024-01-02", 0.02, 0.0)
        assert r.profit_factor == float("inf")

    def test_profit_factor_mixed(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("2024-01-01", 0.05, 0.0)
        r.add_snapshot("2024-01-02", -0.02, 0.0)
        assert r.profit_factor == 2.5

    def test_portfolio_max_dd(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("d1", 0.05, 0.0)
        r.add_snapshot("d2", -0.10, 0.0)
        r.add_snapshot("d3", 0.05, 0.0)
        assert r.portfolio_max_dd < 0


class TestDetectRegime:
    def test_bull_regime(self):
        returns = np.array([0.01] * 30)
        info = detect_regime(returns)
        assert info.regime == "BULL"

    def test_bear_regime(self):
        returns = np.array([-0.01] * 30)
        info = detect_regime(returns)
        assert info.regime == "BEAR"

    def test_insufficient_data(self):
        returns = np.array([0.01] * 5)
        info = detect_regime(returns, lookback=21)
        assert info.regime == "UNKNOWN"

    def test_sideways(self):
        returns = np.array([0.001] * 30)
        info = detect_regime(returns)
        assert info.regime == "SIDEWAYS"


class TestRunMonteCarlo:
    def test_insufficient_data(self):
        returns = [0.01] * 5
        result = run_monte_carlo(returns, n_simulations=50)
        assert result.simulations == 0

    def test_basic_sim(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.015, -0.03, 0.005, -0.02, 0.03, -0.015] * 4
        result = run_monte_carlo(returns, n_simulations=50)
        assert result.simulations == 50
        assert result.mean_return > -5


class TestApplyCosts:
    def test_no_rebalance(self):
        config = BacktestConfig(slippage_bps=5, commission_pct=0.0004, commission_fixed=0.0)
        net, slippage, commission = apply_costs(0.01, False, 1.0, config)
        assert net == 0.01
        assert slippage == 0.0
        assert commission == 0.0

    def test_with_rebalance(self):
        config = BacktestConfig(slippage_bps=5, commission_pct=0.0004, commission_fixed=0.0)
        net, slippage, commission = apply_costs(0.01, True, 1.0, config)
        assert slippage > 0
