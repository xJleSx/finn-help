from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.trading.metrics import PerformanceMetrics, compute_metrics

logger = logging.getLogger(__name__)


@dataclass
class SensitivityResult:
    param_name: str = ""
    param_values: list[float] = field(default_factory=list)
    sharpe_values: list[float] = field(default_factory=list)
    return_values: list[float] = field(default_factory=list)
    max_dd_values: list[float] = field(default_factory=list)
    win_rate_values: list[float] = field(default_factory=list)
    base_metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)

    @property
    def elasticity(self) -> float:
        """% change in Sharpe per 1% change in parameter."""
        if len(self.param_values) < 3 or len(self.sharpe_values) < 3:
            return 0.0
        p = np.array(self.param_values)
        s = np.array(self.sharpe_values)
        base_p = self.param_values[len(self.param_values) // 2]
        if base_p == 0:
            return 0.0
        pct_p = (p - base_p) / base_p
        base_s = s[len(s) // 2]
        if base_s == 0:
            return 0.0
        pct_s = (s - base_s) / base_s
        mask = ~(np.isnan(pct_p) | np.isnan(pct_s) | np.isinf(pct_p) | np.isinf(pct_s))
        if np.sum(mask) < 3:
            return 0.0
        slope = float(np.polyfit(pct_p[mask], pct_s[mask], 1)[0])
        return slope

    def to_dict(self) -> dict[str, Any]:
        return {
            "param_name": self.param_name,
            "param_values": self.param_values,
            "sharpe_values": self.sharpe_values,
            "return_values": self.return_values,
            "max_dd_values": self.max_dd_values,
            "win_rate_values": self.win_rate_values,
            "elasticity": self.elasticity,
            "base": self.base_metrics.to_dict(),
        }


def commission_sensitivity(
    base_equity: list[float],
    commission_rates: list[float] | None = None,
    annual_factor: int = 252,
) -> SensitivityResult:
    if commission_rates is None:
        commission_rates = [0.0, 0.0001, 0.0003, 0.0005, 0.001, 0.002, 0.003, 0.005]

    result = SensitivityResult(param_name="commission_pct", base_metrics=compute_metrics(base_equity, annual_factor=annual_factor))

    base_returns = np.diff(np.array(base_equity, dtype=float)) / np.array(base_equity[:-1], dtype=float)

    for rate in commission_rates:
        adj_returns = base_returns - rate
        adj_equity = [base_equity[0]]
        for r in adj_returns:
            adj_equity.append(adj_equity[-1] * (1 + r))
        metrics = compute_metrics(adj_equity, annual_factor=annual_factor)
        result.param_values.append(rate)
        result.sharpe_values.append(metrics.sharpe)
        result.return_values.append(metrics.total_return)
        result.max_dd_values.append(metrics.max_drawdown)
        result.win_rate_values.append(metrics.win_rate)

    return result


def slippage_sensitivity(
    base_equity: list[float],
    slippage_bps_values: list[int] | None = None,
    annual_factor: int = 252,
) -> SensitivityResult:
    if slippage_bps_values is None:
        slippage_bps_values = [0, 1, 3, 5, 10, 20, 30, 50]

    result = SensitivityResult(param_name="slippage_bps", base_metrics=compute_metrics(base_equity, annual_factor=annual_factor))

    base_returns = np.diff(np.array(base_equity, dtype=float)) / np.array(base_equity[:-1], dtype=float)

    for bps in slippage_bps_values:
        slip_pct = bps / 10_000
        adj_returns = base_returns - slip_pct
        adj_equity = [base_equity[0]]
        for r in adj_returns:
            adj_equity.append(adj_equity[-1] * (1 + r))
        metrics = compute_metrics(adj_equity, annual_factor=annual_factor)
        result.param_values.append(float(bps))
        result.sharpe_values.append(metrics.sharpe)
        result.return_values.append(metrics.total_return)
        result.max_dd_values.append(metrics.max_drawdown)
        result.win_rate_values.append(metrics.win_rate)

    return result


def multi_param_sensitivity(
    base_equity: list[float],
    scenarios: list[dict[str, float]],
    annual_factor: int = 252,
) -> list[dict[str, Any]]:
    base_returns = np.diff(np.array(base_equity, dtype=float)) / np.array(base_equity[:-1], dtype=float)

    results = []
    for scenario in scenarios:
        adj_returns = base_returns.copy()
        for param, value in scenario.items():
            if param in ("commission_pct", "commission"):
                adj_returns -= value
            elif param in ("slippage_bps", "slippage"):
                adj_returns -= value / 10_000

        adj_equity = [base_equity[0]]
        for r in adj_returns:
            adj_equity.append(adj_equity[-1] * (1 + r))

        metrics = compute_metrics(adj_equity, annual_factor=annual_factor)
        results.append({"scenario": scenario, "metrics": metrics.to_dict()})

    return results
