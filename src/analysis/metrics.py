from __future__ import annotations

import numpy as np
import pandas as pd


def compute_returns(prices: list[float]) -> np.ndarray:
    arr = np.array(prices, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return np.array([], dtype=float)
    return np.diff(arr) / arr[:-1]


def compute_sharpe(returns: np.ndarray, annual_factor: int = 252) -> float:
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * np.sqrt(annual_factor))


def compute_sortino(returns: np.ndarray, annual_factor: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    negative = returns[returns < 0]
    downside = np.std(negative) if len(negative) > 0 else 0.0
    if downside == 0:
        return 0.0
    return float(np.mean(returns) / downside * np.sqrt(annual_factor))


def compute_max_drawdown(prices: list[float]) -> float:
    arr = np.array(prices, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return 0.0
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(np.min(dd))


def compute_calmar(returns: np.ndarray, prices: list[float]) -> float:
    ann_return = float(np.mean(returns) * 252)
    mdd = abs(compute_max_drawdown(prices))
    if mdd == 0:
        return 0.0
    return ann_return / mdd


def compute_cvar(returns: pd.Series | np.ndarray, confidence: float = 0.95) -> float:
    returns_arr = returns.values if isinstance(returns, pd.Series) else np.asarray(returns, dtype=float)
    var = np.percentile(returns_arr, (1 - confidence) * 100)
    return float(np.mean(returns_arr[returns_arr < var]))


def compute_omega_ratio(returns: pd.Series | np.ndarray, target_return: float = 0.0) -> float:
    returns_arr = returns.values if isinstance(returns, pd.Series) else np.asarray(returns, dtype=float)
    excess = returns_arr - target_return
    gains = excess[excess > 0].sum()
    losses = -excess[excess < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def compute_information_ratio(returns: pd.Series | np.ndarray, benchmark_returns: pd.Series | np.ndarray) -> float:
    returns_arr = returns.values if isinstance(returns, pd.Series) else np.asarray(returns, dtype=float)
    benchmark_arr = benchmark_returns.values if isinstance(benchmark_returns, pd.Series) else np.asarray(benchmark_returns, dtype=float)
    excess = returns_arr - benchmark_arr
    tracking_error = np.std(excess, ddof=1)
    if tracking_error == 0:
        return 0.0
    return float(np.mean(excess) / tracking_error)


def compute_calmar_ratio(returns: pd.Series | np.ndarray, periods_per_year: int = 252) -> float:
    returns_arr = returns.values if isinstance(returns, pd.Series) else np.asarray(returns, dtype=float)
    total_ret = np.prod(1 + returns_arr) - 1
    n = len(returns_arr)
    cagr = (1 + total_ret) ** (periods_per_year / n) - 1 if n > 0 else 0.0
    eq = np.cumprod(1 + returns_arr)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    max_dd = abs(float(np.min(dd)))
    if max_dd == 0:
        return 0.0
    return float(cagr / max_dd)


def compute_max_drawdown_details(equity_curve: pd.Series | np.ndarray) -> dict[str, int | float]:
    eq_arr = equity_curve.values if isinstance(equity_curve, pd.Series) else np.asarray(equity_curve, dtype=float)
    eq = np.asarray(eq_arr, dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    trough_idx = np.argmin(dd)
    if dd[trough_idx] == 0:
        return {"start_idx": 0, "end_idx": 0, "recovery_idx": 0, "depth": 0.0, "duration": 0}
    peak_idx = int(np.argmax(eq[: trough_idx + 1]))
    peak_val = eq[peak_idx]
    recovery_idx = trough_idx
    for i in range(trough_idx + 1, len(eq)):
        if eq[i] >= peak_val:
            recovery_idx = i
            break
    return {
        "start_idx": peak_idx,
        "end_idx": int(trough_idx),
        "recovery_idx": int(recovery_idx),
        "depth": float(dd[trough_idx]),
        "duration": int(recovery_idx - peak_idx),
    }


def monthly_returns_table(returns: pd.Series) -> pd.DataFrame:
    if not isinstance(returns, pd.Series):
        raise TypeError("monthly_returns_table requires a pandas Series with DatetimeIndex")
    monthly = returns.groupby([returns.index.year, returns.index.month]).apply(lambda x: (1 + x).prod() - 1)
    table = monthly.unstack(level=1)
    table.columns = [f"{m:02d}" for m in table.columns]
    table.index.name = "Year"
    return table


def yearly_returns_table(returns: pd.Series, periods_per_year: int = 252) -> pd.DataFrame:
    if not isinstance(returns, pd.Series):
        raise TypeError("yearly_returns_table requires a pandas Series with DatetimeIndex")
    years = returns.groupby(returns.index.year)

    def yearly_stats(group: pd.Series) -> pd.Series:
        r = group.values
        n = len(r)
        ret = float(np.prod(1 + r) - 1)
        cagr = float((1 + ret) ** (periods_per_year / n) - 1) if n > 0 else 0.0
        vol = float(np.std(r, ddof=1) * np.sqrt(periods_per_year)) if n > 1 else 0.0
        sharpe = float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(periods_per_year)) if n > 1 and np.std(r, ddof=1) > 0 else 0.0
        eq = np.cumprod(1 + r)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        max_dd = float(np.min(dd))
        return pd.Series(
            {
                "Return": ret,
                "CAGR": cagr,
                "Volatility": vol,
                "Sharpe": sharpe,
                "Max DD": max_dd,
            }
        )

    table = years.apply(yearly_stats)
    table.index.name = "Year"
    return table


def benchmark_comparison(
    returns: pd.Series | np.ndarray,
    benchmark_returns: pd.Series | np.ndarray,
    periods_per_year: int = 252,
) -> dict[str, float]:
    returns_arr = returns.values if isinstance(returns, pd.Series) else np.asarray(returns, dtype=float)
    benchmark_arr = benchmark_returns.values if isinstance(benchmark_returns, pd.Series) else np.asarray(benchmark_returns, dtype=float)
    cov = np.cov(returns_arr, benchmark_arr, ddof=1)
    beta = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else 0.0
    alpha = (np.mean(returns_arr) - beta * np.mean(benchmark_arr)) * periods_per_year
    corr = np.corrcoef(returns_arr, benchmark_arr)[0, 1]
    tracking_error = np.std(returns_arr - benchmark_arr, ddof=1)
    ann_tracking_error = tracking_error * np.sqrt(periods_per_year)
    info_ratio = (np.mean(returns_arr - benchmark_arr) / tracking_error * np.sqrt(periods_per_year)) if tracking_error > 0 else 0.0
    return {
        "Alpha": float(alpha),
        "Beta": float(beta),
        "Correlation": float(corr),
        "Tracking Error": float(ann_tracking_error),
        "Information Ratio": float(info_ratio),
    }


def compute_win_rate(trades: np.ndarray | list[float]) -> float:
    trades_arr = np.asarray(trades, dtype=float)
    if len(trades_arr) == 0:
        return 0.0
    return float(np.sum(trades_arr > 0) / len(trades_arr))


def compute_profit_factor(trades: np.ndarray | list[float]) -> float:
    trades_arr = np.asarray(trades, dtype=float)
    gross_profit = trades_arr[trades_arr > 0].sum()
    gross_loss = abs(trades_arr[trades_arr < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)
