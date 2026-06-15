from __future__ import annotations

import numpy as np
import pytest

from src.analysis.backtest import BacktestResult, _max_drawdown, _returns, _sharpe, _sortino


class TestBacktestHelpers:
    def test_returns_empty(self):
        r = _returns([])
        assert len(r) == 0

    def test_returns_single(self):
        r = _returns([100.0])
        assert len(r) == 0

    def test_returns_two_values(self):
        r = _returns([100.0, 110.0])
        assert len(r) == 1
        assert r[0] == pytest.approx(0.1)

    def test_sharpe_constant_returns(self):
        r = np.ones(100) * 0.01
        s = _sharpe(r, annual_factor=252)
        assert np.isinf(s) or s > 0

    def test_sharpe_zero_vol(self):
        r = np.zeros(100)
        assert _sharpe(r) == 0.0

    def test_sortino_constant(self):
        r = np.ones(100) * 0.01
        assert _sortino(r) >= 0

    def test_sortino_negative(self):
        r = -np.ones(100) * 0.01
        assert _sortino(r) < 0

    def test_max_drawdown_all_up(self):
        prices = [100, 110, 120, 130]
        assert _max_drawdown(prices) == 0.0

    def test_max_drawdown_with_crash(self):
        prices = [100, 120, 80, 110]
        dd = _max_drawdown(prices)
        assert abs(dd) > 0.3
        assert abs(dd) < 0.4


class TestBacktestResult:
    def test_empty_result(self):
        r = BacktestResult(capital=100_000)
        assert r.portfolio_return == 0
        assert r.benchmark_return == 0
        assert r.portfolio_sharpe == 0.0
        assert r.portfolio_sortino == 0.0
        assert r.portfolio_max_dd == 0.0

    def test_single_positive_period(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("2025-01-01", 0.05, 0.02)
        assert r.portfolio_return == pytest.approx(0.05)
        assert r.benchmark_return == pytest.approx(0.02)

    def test_multiple_periods(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("2025-01-01", 0.1, 0.05)
        r.add_snapshot("2025-02-01", -0.05, -0.03)
        r.add_snapshot("2025-03-01", 0.07, 0.04)
        assert r.portfolio_return == pytest.approx(1.1 * 0.95 * 1.07 - 1, rel=1e-4)
        assert r.benchmark_return == pytest.approx(1.05 * 0.97 * 1.04 - 1, rel=1e-4)

    def test_max_drawdown_on_straight_line(self):
        r = BacktestResult(capital=100_000)
        for i in range(10):
            r.add_snapshot(f"2025-{i + 1:02d}-01", 0.02, 0.01)
        assert r.portfolio_max_dd == 0.0

    def test_summary_contains_keys(self):
        r = BacktestResult(capital=100_000)
        r.add_snapshot("2025-01-01", 0.05, 0.02)
        s = r.summary()
        assert "Доходность" in s
        assert "Sharpe" in s or "Шарп" in s
        assert "Sortino" in s
        assert "просадка" in s or "падение" in s
