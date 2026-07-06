import numpy as np


def compute_returns(prices: list[float]) -> np.ndarray:
    arr = np.array(prices, dtype=float)
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
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(np.min(dd))


def compute_calmar(returns: np.ndarray, prices: list[float]) -> float:
    ann_return = float(np.mean(returns) * 252)
    mdd = abs(compute_max_drawdown(prices))
    if mdd == 0:
        return 0.0
    return ann_return / mdd
