from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize


class ViewDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class MarketView:
    ticker: str
    direction: ViewDirection | str
    confidence: float
    magnitude: float

    def __post_init__(self) -> None:
        if isinstance(self.direction, str):
            self.direction = ViewDirection(self.direction)
        self.confidence = np.clip(self.confidence, 0.0, 1.0)


def _compute_implied_returns(
    delta: float,
    cov: np.ndarray,
    market_weights: np.ndarray,
) -> np.ndarray:
    return delta * cov @ market_weights


def _build_view_matrices(
    views: list[MarketView],
    tickers: list[str],
    cov: np.ndarray,
    tau: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(tickers)
    k = len(views)
    if k == 0:
        return np.zeros((0, n)), np.zeros(0), np.zeros((0, 0))

    ticker_to_idx = {t: i for i, t in enumerate(tickers)}
    P = np.zeros((k, n))
    Q = np.zeros(k)
    for i, v in enumerate(views):
        idx = ticker_to_idx.get(v.ticker)
        if idx is None:
            msg = f"Ticker {v.ticker} not found in universe"
            raise ValueError(msg)
        P[i, idx] = 1.0
        Q[i] = v.magnitude / 100.0
    tau_scaled = tau * cov
    Omega = np.zeros((k, k))
    for i, v in enumerate(views):
        c = v.confidence
        scaled_var = float(P[i] @ tau_scaled @ P[i])
        if c <= 0:
            Omega[i, i] = 1e12
        elif c >= 1.0:
            Omega[i, i] = scaled_var * 1e-6
        else:
            Omega[i, i] = scaled_var * (1.0 / c - 1.0)
    return P, Q, Omega


def _black_litterman_posterior(
    Pi: np.ndarray,
    Sigma: np.ndarray,
    tau: float,
    P: np.ndarray,
    Q: np.ndarray,
    Omega: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    tau_Sigma = tau * Sigma
    tau_Sigma_inv = np.linalg.inv(tau_Sigma)
    if P.shape[0] == 0:
        return Pi.copy(), Sigma.copy()
    Omega_inv = np.linalg.inv(Omega)
    M_inv = tau_Sigma_inv + P.T @ Omega_inv @ P
    M = np.linalg.inv(M_inv)
    mu_posterior = M @ (tau_Sigma_inv @ Pi + P.T @ Omega_inv @ Q)
    Sigma_posterior = Sigma + M
    return mu_posterior, Sigma_posterior


class MeanVarianceOptimizer:
    def __init__(
        self,
        expected_returns: np.ndarray,
        covariance: np.ndarray,
        tickers: list[str],
        risk_free_rate: float = 0.0,
    ) -> None:
        self.mu = np.asarray(expected_returns, dtype=float)
        self.Sigma = np.asarray(covariance, dtype=float)
        self.tickers = list(tickers)
        self.n = len(tickers)
        self.r_f = risk_free_rate

    @staticmethod
    def _portfolio_stats(weights: np.ndarray, mu: np.ndarray, Sigma: np.ndarray) -> tuple[float, float]:
        ret = weights @ mu
        vol = np.sqrt(weights @ Sigma @ weights)
        return ret, vol

    def max_sharpe(self) -> dict[str, Any]:
        constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        bounds = [(0.0, 1.0)] * self.n

        def neg_sharpe(w: np.ndarray) -> float:
            ret, vol = self._portfolio_stats(w, self.mu, self.Sigma)
            if vol < 1e-12:
                return -1e12
            return -(ret - self.r_f) / vol

        guess = np.ones(self.n) / self.n
        res = minimize(neg_sharpe, guess, method="SLSQP", bounds=bounds, constraints=constraints)
        w = res.x / res.x.sum()
        ret, vol = self._portfolio_stats(w, self.mu, self.Sigma)
        return {
            "weights": dict(zip(self.tickers, w)),
            "return": ret,
            "volatility": vol,
            "sharpe": (ret - self.r_f) / vol if vol > 1e-12 else 0.0,
        }

    def min_volatility(self) -> dict[str, Any]:
        constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        bounds = [(0.0, 1.0)] * self.n

        def portfolio_vol(w: np.ndarray) -> float:
            return float(np.sqrt(w @ self.Sigma @ w))

        guess = np.ones(self.n) / self.n
        res = minimize(portfolio_vol, guess, method="SLSQP", bounds=bounds, constraints=constraints)
        w = res.x / res.x.sum()
        ret, vol = self._portfolio_stats(w, self.mu, self.Sigma)
        return {
            "weights": dict(zip(self.tickers, w)),
            "return": ret,
            "volatility": vol,
            "sharpe": (ret - self.r_f) / vol if vol > 1e-12 else 0.0,
        }

    def target_return(self, target: float) -> dict[str, Any]:
        constraints = [
            {"type": "eq", "fun": lambda w: w.sum() - 1.0},
            {"type": "eq", "fun": lambda w: w @ self.mu - target},
        ]
        bounds = [(0.0, 1.0)] * self.n

        def portfolio_vol(w: np.ndarray) -> float:
            return float(np.sqrt(w @ self.Sigma @ w))

        guess = np.ones(self.n) / self.n
        res = minimize(portfolio_vol, guess, method="SLSQP", bounds=bounds, constraints=constraints)
        w = res.x / res.x.sum()
        ret, vol = self._portfolio_stats(w, self.mu, self.Sigma)
        return {
            "weights": dict(zip(self.tickers, w)),
            "return": ret,
            "volatility": vol,
            "sharpe": (ret - self.r_f) / vol if vol > 1e-12 else 0.0,
        }

    def efficient_frontier(self, points: int = 20) -> pd.DataFrame:
        opt_max = self.max_sharpe()
        max_ret = opt_max["return"]
        min_vol_result = self.min_volatility()
        min_ret = min_vol_result["return"]

        if max_ret <= min_ret:
            return pd.DataFrame()

        targets = np.linspace(min_ret, max_ret, points)
        records: list[dict[str, Any]] = []
        for t in targets:
            try:
                res = self.target_return(t)
                records.append(res)
            except (ValueError, RuntimeError):
                continue
        return pd.DataFrame(records)

    def optimize(self, method: str = "max_sharpe", target: float | None = None) -> dict[str, Any]:
        if method == "max_sharpe":
            return self.max_sharpe()
        if method == "min_volatility":
            return self.min_volatility()
        if method == "target_return":
            if target is None:
                msg = "target must be provided for target_return method"
                raise ValueError(msg)
            return self.target_return(target)
        msg = f"Unknown method: {method}"
        raise ValueError(msg)


class BlackLittermanAllocator:
    def __init__(
        self,
        market_weights: dict[str, float],
        covariance: pd.DataFrame,
        tau: float = 0.05,
        risk_aversion: float | None = None,
    ) -> None:
        self.tickers = list(market_weights.keys())
        self.w_mkt = np.array([market_weights[t] for t in self.tickers])
        self.w_mkt = self.w_mkt / self.w_mkt.sum()
        self.Sigma = covariance.loc[self.tickers, self.tickers].values
        self.tau = tau
        self.delta = risk_aversion if risk_aversion is not None else self._estimate_risk_aversion()

    def _estimate_risk_aversion(self) -> float:
        ann_ret = 0.08
        ann_vol = 0.15
        return ann_ret / (ann_vol**2)

    def implied_returns(self) -> pd.Series:
        Pi = _compute_implied_returns(self.delta, self.Sigma, self.w_mkt)
        return pd.Series(Pi, index=self.tickers)

    def allocate(
        self,
        views: list[MarketView],
        optimizer_method: str = "max_sharpe",
        target_return: float | None = None,
    ) -> dict[str, Any]:
        Pi = _compute_implied_returns(self.delta, self.Sigma, self.w_mkt)
        P, Q, Omega = _build_view_matrices(views, self.tickers, self.Sigma, self.tau)
        mu_posterior, Sigma_posterior = _black_litterman_posterior(Pi, self.Sigma, self.tau, P, Q, Omega)

        opt = MeanVarianceOptimizer(mu_posterior, Sigma_posterior, self.tickers)
        result: dict[str, Any] = opt.optimize(optimizer_method, target_return)
        result["posterior_returns"] = pd.Series(mu_posterior, index=self.tickers)
        result["implied_returns"] = pd.Series(Pi, index=self.tickers)
        return result
