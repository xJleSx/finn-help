from __future__ import annotations

import logging
from typing import Any, TypedDict

import numpy as np
import pandas as pd
from scipy.optimize import minimize

logger = logging.getLogger(__name__)

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Advanced volatility estimators
# ---------------------------------------------------------------------------


def parkinson_volatility(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    period: int = 20,
    annualize: bool = True,
) -> np.ndarray:
    """Parkinson (1980) extreme-value volatility estimator using high/low range.

    Parameters
    ----------
    highs : array-like
        High prices.
    lows : array-like
        Low prices.
    period : int, default 20
        Rolling window length.
    annualize : bool, default True
        Whether to multiply by sqrt(252).

    Returns
    -------
    np.ndarray
        Parkinson volatility estimate for each point (NaN for first ``period-1``).
    """
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    ratio = np.log(highs / lows)
    squared = ratio**2
    divisor = 4.0 * np.log(2.0)
    out = np.full_like(highs, np.nan)
    if len(highs) < period:
        return out
    for i in range(period - 1, len(highs)):
        out[i] = np.sqrt(np.nanmean(squared[i - period + 1 : i + 1]) / divisor)
    if annualize:
        out *= np.sqrt(TRADING_DAYS)
    return out


def garman_klass_volatility(
    opens: np.ndarray | pd.Series,
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    period: int = 20,
    annualize: bool = True,
) -> np.ndarray:
    """Garman-Klass (1980) OHLC volatility estimator (non-overlapping version).

    Uses the open, high, low and close to produce a more efficient estimate
    than close-to-close alone.

    Parameters
    ----------
    opens, highs, lows, closes : array-like
        OHLC prices.
    period : int, default 20
        Rolling window length.
    annualize : bool, default True
        Whether to multiply by sqrt(252).

    Returns
    -------
    np.ndarray
        Garman-Klass volatility for each point (NaN for first ``period-1``).
    """
    opens = np.asarray(opens, dtype=float)
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    hl = np.log(highs / lows) ** 2
    co = np.log(closes / opens) ** 2
    term = 0.5 * hl - (2.0 * np.log(2.0) - 1.0) * co
    out = np.full_like(closes, np.nan)
    if len(closes) < period:
        return out
    for i in range(period - 1, len(closes)):
        out[i] = np.sqrt(np.nanmean(term[i - period + 1 : i + 1]))
    if annualize:
        out *= np.sqrt(TRADING_DAYS)
    return out


def yang_zhang_volatility(
    opens: np.ndarray | pd.Series,
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    period: int = 20,
    annualize: bool = True,
) -> np.ndarray:
    """Yang-Zhang (2000) estimator combining overnight and intraday volatility.

    Accounts for both open-to-close (intraday) and close-to-open (overnight)
    jumps, making it unbiased even in the presence of price jumps.

    Parameters
    ----------
    opens, highs, lows, closes : array-like
        OHLC prices.
    period : int, default 20
        Rolling window length.
    annualize : bool, default True
        Whether to multiply by sqrt(252).

    Returns
    -------
    np.ndarray
        Yang-Zhang volatility for each point (NaN for first ``period-1``).
    """
    opens = np.asarray(opens, dtype=float)
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)

    log_ho = np.log(highs / opens)
    log_lo = np.log(lows / opens)
    log_co = np.log(closes / opens)

    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

    close_prev = np.roll(closes, 1)
    close_prev[0] = opens[0]
    log_oc = np.log(opens / close_prev)
    log_cc = np.log(closes / opens)

    out = np.full_like(closes, np.nan)
    if len(closes) < period:
        return out
    for i in range(period - 1, len(closes)):
        slice_rs = rs[i - period + 1 : i + 1]
        slice_oc = log_oc[i - period + 1 : i + 1]
        slice_cc = log_cc[i - period + 1 : i + 1]
        overnight_var = np.nanvar(slice_oc)
        intraday_var = np.nanvar(slice_cc)
        rs_mean = np.nanmean(slice_rs)
        k = 0.34 / (1.34 + (period + 1) / (period - 1))
        out[i] = np.sqrt(overnight_var + k * intraday_var + (1.0 - k) * rs_mean)
    if annualize:
        out *= np.sqrt(TRADING_DAYS)
    return out


def ewma_volatility(
    returns: np.ndarray | pd.Series,
    lam: float = 0.94,
    annualize: bool = True,
) -> np.ndarray:
    """EWMA (exponentially weighted moving average) volatility estimator.

    Uses the RiskMetrics™ lambda of 0.94 by default.

    Parameters
    ----------
    returns : array-like
        Log or simple returns series.
    lam : float, default 0.94
        Decay factor (0 < lam < 1).
    annualize : bool, default True
        Whether to multiply by sqrt(252).

    Returns
    -------
    np.ndarray
        EWMA volatility series of the same length (first value = NaN).
    """
    r = np.asarray(returns, dtype=float)
    squared = r**2
    out = np.full_like(r, np.nan)
    if len(r) < 2:
        return out
    var = squared[0]
    out[0] = np.sqrt(var)
    for i in range(1, len(r)):
        var = lam * var + (1.0 - lam) * squared[i]
        out[i] = np.sqrt(var)
    if annualize:
        out *= np.sqrt(TRADING_DAYS)
    return out


def garch_volatility(
    returns: np.ndarray | pd.Series,
) -> tuple[float, float, float, float, float]:
    """GARCH(1,1) parameter estimation via MLE with scipy.

    Returns
    -------
    tuple[float, float, float, float, float]
        (omega, alpha, beta, long_run_var, forecast_vol).
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    init_var = float(np.var(r, ddof=0))

    def _neg_log_likelihood(params: np.ndarray) -> float:
        omega, alpha, beta = params
        if omega <= 0 or alpha <= 0 or beta <= 0 or alpha + beta >= 1:
            return 1e10
        sigma2 = np.full(n, init_var)
        for t in range(1, n):
            sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
        ll = 0.0
        for t in range(n):
            if sigma2[t] <= 0:
                return 1e10
            ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2[t]) + r[t] ** 2 / sigma2[t])
        return -ll

    result = minimize(
        _neg_log_likelihood,
        x0=np.array([0.01 * init_var, 0.1, 0.85]),
        bounds=((1e-8, None), (0.0, 1.0), (0.0, 1.0)),
        method="L-BFGS-B",
    )
    omega, alpha, beta = result.x
    long_run_var = omega / (1.0 - alpha - beta)
    forecast_vol = float(np.sqrt(long_run_var)) * np.sqrt(TRADING_DAYS)
    return (omega, alpha, beta, long_run_var, forecast_vol)


def volatility_cones(
    df: pd.DataFrame,
    windows: list[int] | None = None,
) -> dict[str, dict[str, float]]:
    """Volatility cones showing realised volatility percentiles across windows.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain at least a ``close`` column.
    windows : list[int], optional
        Window lengths to evaluate (default [5, 10, 20, 60, 120]).

    Returns
    -------
    dict[str, dict[str, float]]
        ``cones[window_label] = {"5%": ..., "25%": ..., "50%": ..., "75%": ..., "95%": ...}``
    """
    if windows is None:
        windows = [5, 10, 20, 60, 120]
    closes = np.asarray(df["close"], dtype=float)
    returns = np.diff(closes) / closes[:-1]
    cones: dict[str, dict[str, float]] = {}
    for w in windows:
        vols = []
        for i in range(len(returns) - w + 1):
            v = float(np.std(returns[i : i + w], ddof=1)) * np.sqrt(TRADING_DAYS)
            vols.append(v)
        if not vols:
            cones[str(w)] = {"5%": 0.0, "25%": 0.0, "50%": 0.0, "75%": 0.0, "95%": 0.0}
        else:
            sorted_v = sorted(vols)
            n = len(sorted_v)
            cones[str(w)] = {
                "5%": float(sorted_v[int(n * 0.05)]),
                "25%": float(sorted_v[int(n * 0.25)]),
                "50%": float(sorted_v[int(n * 0.50)]),
                "75%": float(sorted_v[int(n * 0.75)]),
                "95%": float(sorted_v[int(n * 0.95)]),
            }
    return cones


# ---------------------------------------------------------------------------
# Volatility forecaster
# ---------------------------------------------------------------------------


class VolatilityForecaster:
    """Multi-step volatility forecasting using EWMA or GARCH(1,1)."""

    @staticmethod
    def ewma_forecast(
        returns: np.ndarray | pd.Series,
        lam: float = 0.94,
        steps: int = 10,
    ) -> np.ndarray:
        """Multi-step EWMA volatility forecast (flat forward).

        The *k*-step ahead forecast is the same as the one-step-ahead
        estimate because EWMA is a random-walk-style model.

        Parameters
        ----------
        returns : array-like
            Historical returns.
        lam : float, default 0.94
            Decay factor.
        steps : int, default 10
            Forecast horizon.

        Returns
        -------
        np.ndarray
            Array of length ``steps`` with the forecast annualised vol.
        """
        ewma = ewma_volatility(returns, lam=lam, annualize=True)
        last_vol = float(ewma[~np.isnan(ewma)][-1]) if np.any(~np.isnan(ewma)) else 0.0
        return np.full(steps, last_vol)

    @staticmethod
    def garch_forecast(
        returns: np.ndarray | pd.Series,
        steps: int = 10,
    ) -> np.ndarray:
        """Multi-step GARCH(1,1) term-structure forecast.

        The *k*-step ahead conditional variance converges to the
        unconditional long-run variance as *k → ∞*.

        Parameters
        ----------
        returns : array-like
            Historical returns.
        steps : int, default 10
            Forecast horizon.

        Returns
        -------
        np.ndarray
            Array of length ``steps`` with the forecast annualised vol.
        """
        omega, alpha, beta, long_run_var, _ = garch_volatility(returns)
        one_step_var = omega + alpha * np.var(returns, ddof=0) + beta * long_run_var
        forecasts = np.empty(steps)
        var_t = one_step_var
        for k in range(steps):
            if k == 0:
                forecasts[k] = np.sqrt(var_t) * np.sqrt(TRADING_DAYS)
            else:
                var_t = long_run_var + (alpha + beta) ** k * (var_t - long_run_var)
                forecasts[k] = np.sqrt(var_t) * np.sqrt(TRADING_DAYS)
        return forecasts

    @staticmethod
    def forecast_term_structure(
        returns: np.ndarray | pd.Series,
        method: str = "ewma",
        steps: int = 10,
    ) -> np.ndarray:
        """Unified wrapper for volatility term-structure forecasts.

        Parameters
        ----------
        returns : array-like
            Historical returns.
        method : str, default ``"ewma"``
            One of ``"ewma"`` or ``"garch"``.
        steps : int, default 10
            Forecast horizon.

        Returns
        -------
        np.ndarray
            Forecast annualised volatility for each step.
        """
        if method == "ewma":
            return VolatilityForecaster.ewma_forecast(returns, steps=steps)
        if method == "garch":
            return VolatilityForecaster.garch_forecast(returns, steps=steps)
        raise ValueError(f"Unknown method '{method}'; use 'ewma' or 'garch'.")


class _VolatilityThresholds(TypedDict):
    label: str
    threshold_atr: float
    threshold_hv: float


VOLATILITY_REGIMES: dict[str, _VolatilityThresholds] = {
    "LOW": {"label": "Низкая", "threshold_atr": 0.012, "threshold_hv": 0.15},
    "NORMAL": {"label": "Нормальная", "threshold_atr": 0.025, "threshold_hv": 0.30},
    "HIGH": {"label": "Высокая", "threshold_atr": float("inf"), "threshold_hv": float("inf")},
}


class VolatilityRegimeDetector:
    def detect(self, df: pd.DataFrame, ind_df: pd.DataFrame) -> dict[str, Any]:
        if df.empty:
            return {"regime": "NORMAL", "atr_ratio": 0.0, "hv": 0.0, "adjustment": 1.0}

        close = np.asarray(df["close"], dtype=float)
        returns = np.diff(close) / close[:-1]
        hv = float(np.std(returns) * np.sqrt(252)) if len(returns) > 1 else 0.0

        atr_ratio = 0.0
        if not ind_df.empty and "atr" in ind_df.columns:
            last_atr = ind_df["atr"].iloc[-1]
            last_close = close[-1]
            if pd.notna(last_atr) and last_close > 0:
                atr_ratio = last_atr / last_close

        regime = self._classify(atr_ratio, hv)

        adjustment = self._weight_adjustment(regime)

        return {
            "regime": regime,
            "atr_ratio": round(atr_ratio, 4),
            "hv": round(hv, 4),
            "adjustment": adjustment,
        }

    def _classify(self, atr_ratio: float, hv: float) -> str:
        low_atr: float = VOLATILITY_REGIMES["LOW"]["threshold_atr"]
        low_hv: float = VOLATILITY_REGIMES["LOW"]["threshold_hv"]
        norm_atr: float = VOLATILITY_REGIMES["NORMAL"]["threshold_atr"]
        norm_hv: float = VOLATILITY_REGIMES["NORMAL"]["threshold_hv"]
        if atr_ratio < low_atr and hv < low_hv:
            return "LOW"
        if atr_ratio < norm_atr or hv < norm_hv:
            return "NORMAL"
        return "HIGH"

    def _weight_adjustment(self, regime: str) -> dict[str, float]:
        if regime == "HIGH":
            return {
                "technical_mult": 0.7,
                "fundamental_mult": 1.3,
                "geo_mult": 1.5,
                "ml_mult": 0.6,
            }
        if regime == "LOW":
            return {
                "technical_mult": 1.2,
                "fundamental_mult": 0.8,
                "geo_mult": 0.6,
                "ml_mult": 1.2,
            }
        return {
            "technical_mult": 1.0,
            "fundamental_mult": 1.0,
            "geo_mult": 1.0,
            "ml_mult": 1.0,
        }
