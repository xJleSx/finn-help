import logging

import numpy as np

logger = logging.getLogger(__name__)


def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    if len(returns) < 10:
        return 0.0
    return float(abs(np.percentile(returns, (1 - confidence) * 100)))


def parametric_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    if len(returns) < 10:
        return 0.0
    from scipy import stats
    mu = np.mean(returns)
    sigma = np.std(returns)
    z = stats.norm.ppf(1 - confidence)
    return float(abs(mu + z * sigma))


def compute_var(price_series: list[float], confidence: float = 0.95) -> dict:
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


def compute_stop_loss(price: float, atr: float | None, multiplier: float = 2.0) -> dict | None:
    if atr is None or atr <= 0 or price <= 0:
        return None
    stop_distance = atr * multiplier
    return {
        "stop_loss": round(price - stop_distance, 2),
        "stop_loss_pct": round(-(stop_distance / price) * 100, 2),
        "atr_multiple": multiplier,
    }


def compute_position_size(
    capital: float,
    price: float,
    risk_per_trade_pct: float = 2.0,
    stop_loss_pct: float | None = None,
) -> dict:
    if price <= 0:
        return {"shares": 0, "amount": 0.0, "risk_amount": 0.0}

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
    }
