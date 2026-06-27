from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    if len(returns) < 10:
        return 0.0
    return float(abs(np.percentile(returns, (1 - confidence) * 100)))


def compute_var(price_series: list[float], confidence: float = 0.95) -> dict[str, float]:
    arr = np.array(price_series, dtype=float)
    if len(arr) < 10:
        return {"var_95": 0.0, "var_99": 0.0, "cvar_95": 0.0}

    returns = np.diff(arr) / arr[:-1]

    var_95 = historical_var(returns, 0.95)
    var_99 = historical_var(returns, 0.99)

    cvar_95 = float(abs(np.mean(returns[returns <= -var_95]))) if len(returns[returns <= -var_95]) > 0 else var_95

    return {
        "var_95": round(var_95 * 100, 2),
        "var_99": round(var_99 * 100, 2),
        "cvar_95": round(cvar_95 * 100, 2),
    }


def compute_stop_loss(price: float, atr: float | None, multiplier: float = 2.0) -> dict[str, float] | None:
    if atr is None or atr <= 0 or price <= 0:
        return None
    stop_distance = atr * multiplier
    return {
        "stop_loss": round(price - stop_distance, 2),
        "stop_loss_pct": round(-(stop_distance / price) * 100, 2),
        "atr_multiple": multiplier,
    }


def compute_concentration_limit(capital: float, price: float, max_position_pct: float = 20.0) -> dict[str, float | int]:
    if price <= 0:
        return {"shares": 0, "amount": 0.0, "max_pct": max_position_pct}
    max_amount = capital * max_position_pct / 100
    shares = int(max_amount / price)
    return {
        "shares": shares,
        "amount": round(shares * price, 2),
        "max_pct": max_position_pct,
    }


def compute_risk_score(var_95: float, stop_loss_pct: float, atr_ratio: float | None = None) -> float:
    score = 0.0
    score += min(var_95 / 5.0, 3.0)
    score += min(abs(stop_loss_pct) / 5.0, 2.0)
    if atr_ratio is not None:
        score += min(atr_ratio / 3.0, 2.0)
    return round(min(score / 7.0, 1.0), 3)


def kelly_fraction(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    max_kelly: float = 0.25,
) -> float:
    if avg_loss_pct <= 0:
        return 0.0
    b = abs(avg_win_pct / avg_loss_pct)
    p = win_rate
    q = 1 - p
    if b <= 0:
        return 0.0
    kelly = (b * p - q) / b
    return max(0.0, min(kelly, max_kelly))


def compute_position_size(
    capital: float,
    price: float,
    risk_per_trade_pct: float = 2.0,
    stop_loss_pct: float | None = None,
    method: str = "fixed_fractional",
    win_rate: float = 0.0,
    avg_win_pct: float = 0.0,
    avg_loss_pct: float = 0.0,
) -> dict[str, float | int | str]:
    if price <= 0:
        return {"shares": 0, "amount": 0.0, "risk_amount": 0.0}

    if method == "kelly" and win_rate > 0 and avg_win_pct > 0 and avg_loss_pct > 0:
        fraction = kelly_fraction(win_rate, avg_win_pct, avg_loss_pct)
        max_risk_amount = capital * fraction
    else:
        max_risk_amount = capital * risk_per_trade_pct / 100

    if stop_loss_pct and stop_loss_pct < 0:
        risk_per_share = price * abs(stop_loss_pct) / 100
        shares = int(max_risk_amount / risk_per_share) if risk_per_share > 0 else 0
    else:
        shares = int(max_risk_amount / (price * 0.05))

    amount = round(shares * price, 2)
    return {
        "shares": shares,
        "amount": amount,
        "risk_amount": round(max_risk_amount, 2),
        "risk_pct": risk_per_trade_pct,
        "method": method,
    }
