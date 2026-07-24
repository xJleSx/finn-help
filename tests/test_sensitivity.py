from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from src.analysis.sensitivity import (
    SensitivityResult,
    commission_sensitivity,
    multi_param_sensitivity,
    slippage_sensitivity,
)
from src.trading.metrics import PerformanceMetrics


class TestSensitivityResult:
    def test_elasticity_returns_zero_with_fewer_than_3_values(self):
        r = SensitivityResult(param_values=[1.0], sharpe_values=[0.5])
        assert r.elasticity == 0.0

    def test_elasticity_returns_zero_when_base_param_is_zero(self):
        r = SensitivityResult(param_values=[-1, 0, 1], sharpe_values=[0.4, 0.5, 0.6])
        assert r.elasticity == 0.0

    def test_elasticity_returns_zero_when_base_sharpe_is_zero(self):
        r = SensitivityResult(param_values=[1, 2, 3], sharpe_values=[0.0, 0.0, 0.0])
        assert r.elasticity == 0.0

    def test_elasticity_returns_zero_when_nan_or_inf_present(self):
        r = SensitivityResult(param_values=[1, 2, 3], sharpe_values=[np.nan, np.inf, 0.5])
        assert r.elasticity == 0.0

    def test_to_dict_includes_elasticity_and_base(self):
        base = PerformanceMetrics(sharpe=1.5, total_return=0.1)
        r = SensitivityResult(
            param_name="test",
            param_values=[0.1, 0.2, 0.3],
            sharpe_values=[1.0, 1.1, 1.2],
            base_metrics=base,
        )
        d = r.to_dict()
        assert d["param_name"] == "test"
        assert "elasticity" in d
        assert d["base"]["sharpe"] == 1.5


class TestCommissionSensitivity:
    @patch("src.analysis.sensitivity.compute_metrics")
    def test_default_rates(self, mock_cm):
        def side_effect(equity, annual_factor=252):
            n = len(equity)
            return PerformanceMetrics(
                sharpe=1.5 - (n * 0.01),
                total_return=0.2 - (n * 0.001),
                max_drawdown=-0.1 - (n * 0.001),
                win_rate=0.6 - (n * 0.002),
            )

        mock_cm.side_effect = side_effect
        equity = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0]
        result = commission_sensitivity(equity)
        assert result.param_name == "commission_pct"
        assert len(result.param_values) == 8
        assert all(0.0 <= v <= 0.005 for v in result.param_values)
        assert len(result.sharpe_values) == 8
        assert len(result.return_values) == 8
        assert len(result.max_dd_values) == 8
        assert len(result.win_rate_values) == 8
        assert mock_cm.call_count == 8 + 1

    @patch("src.analysis.sensitivity.compute_metrics")
    def test_custom_rates(self, mock_cm):
        mock_cm.return_value = PerformanceMetrics(
            sharpe=0.8, total_return=0.05, max_drawdown=-0.2, win_rate=0.55
        )
        equity = [100.0, 101.0, 99.0, 102.0, 100.0]
        result = commission_sensitivity(equity, commission_rates=[0.001, 0.002])
        assert len(result.param_values) == 2

    @patch("src.analysis.sensitivity.compute_metrics")
    def test_adj_equity_decreases_with_higher_commission(self, mock_cm):
        captured = []

        def side_effect(equity, annual_factor=252):
            captured.append(equity)
            return PerformanceMetrics(
                sharpe=1.0 - (len(captured) * 0.1),
                total_return=0.1,
                max_drawdown=-0.1,
                win_rate=0.5,
            )

        mock_cm.side_effect = side_effect
        equity = [100.0, 102.0, 104.0, 106.0, 108.0]
        commission_sensitivity(equity, commission_rates=[0.0, 0.05])
        base_equity = captured[0]
        adj_0 = captured[1]
        adj_1 = captured[2]
        assert adj_0[-1] <= base_equity[-1]
        assert adj_1[-1] < adj_0[-1]


class TestSlippageSensitivity:
    @patch("src.analysis.sensitivity.compute_metrics")
    def test_default_bps_values(self, mock_cm):
        def side_effect(equity, annual_factor=252):
            n = len(equity)
            return PerformanceMetrics(
                sharpe=1.2 - (n * 0.01),
                total_return=0.15 - (n * 0.001),
                max_drawdown=-0.12 - (n * 0.001),
                win_rate=0.58 - (n * 0.002),
            )

        mock_cm.side_effect = side_effect
        equity = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0]
        result = slippage_sensitivity(equity)
        assert result.param_name == "slippage_bps"
        assert len(result.param_values) == 8
        assert all(isinstance(v, float) for v in result.param_values)

    @patch("src.analysis.sensitivity.compute_metrics")
    def test_higher_slippage_reduces_returns(self, mock_cm):
        captured = []

        def side_effect(equity, annual_factor=252):
            captured.append(equity)
            return PerformanceMetrics(
                sharpe=1.0, total_return=0.1, max_drawdown=-0.1, win_rate=0.5
            )

        mock_cm.side_effect = side_effect
        equity = [100.0, 102.0, 104.0, 106.0, 108.0]
        slippage_sensitivity(equity, slippage_bps_values=[0, 100])
        assert captured[2][-1] < captured[1][-1]


class TestMultiParamSensitivity:
    @patch("src.analysis.sensitivity.compute_metrics")
    def test_commission_scenario(self, mock_cm):
        mock_cm.return_value = PerformanceMetrics(
            sharpe=1.0, total_return=0.1, max_drawdown=-0.1, win_rate=0.55
        )
        equity = [100.0, 102.0, 104.0, 106.0, 108.0]
        scenarios = [{"commission_pct": 0.001}, {"slippage_bps": 10}]
        results = multi_param_sensitivity(equity, scenarios)
        assert len(results) == 2
        assert "scenario" in results[0]
        assert "metrics" in results[0]
        assert results[0]["scenario"]["commission_pct"] == 0.001
        assert results[1]["scenario"]["slippage_bps"] == 10

    @patch("src.analysis.sensitivity.compute_metrics")
    def test_scenario_applies_commission_and_slippage_correctly(self, mock_cm):
        captured = []

        def side_effect(equity, annual_factor=252):
            captured.append(equity)
            return PerformanceMetrics(
                sharpe=1.0, total_return=0.1, max_drawdown=-0.1, win_rate=0.5
            )

        mock_cm.side_effect = side_effect
        equity = [100.0, 110.0, 120.0, 130.0, 140.0]
        scenarios = [{"commission": 0.01}, {"slippage": 50}]
        multi_param_sensitivity(equity, scenarios)
        assert len(captured) == 2
        orig_last = equity[-1]
        comm_last = captured[0][-1]
        slip_last = captured[1][-1]
        assert comm_last < orig_last
        assert slip_last < orig_last

    @patch("src.analysis.sensitivity.compute_metrics")
    def test_empty_scenarios(self, mock_cm):
        mock_cm.return_value = PerformanceMetrics(
            sharpe=1.0, total_return=0.1, max_drawdown=-0.1, win_rate=0.5
        )
        equity = [100.0, 102.0, 104.0]
        results = multi_param_sensitivity(equity, [])
        assert results == []
