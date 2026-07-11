from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr_percentile(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    atr_period: int = 14,
    lookback: int = 100,
) -> pd.Series:
    tr = _true_range(high, low, close)
    atr = tr.ewm(span=atr_period, adjust=False).mean()
    return atr.rolling(lookback, min_periods=lookback).rank(pct=True) * 100


def compute_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    tr = _true_range(high, low, close)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
    )

    smoothed_tr = tr.ewm(span=period, adjust=False).mean()
    smoothed_plus = plus_dm.ewm(span=period, adjust=False).mean()
    smoothed_minus = minus_dm.ewm(span=period, adjust=False).mean()

    plus_di = 100 * smoothed_plus / smoothed_tr.replace(0, np.nan)
    minus_di = 100 * smoothed_minus / smoothed_tr.replace(0, np.nan)

    di_sum = plus_di + minus_di
    di_sum = di_sum.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    return dx.ewm(span=period, adjust=False).mean()


def trend_direction(close: pd.Series, period: int = 20) -> int:
    if len(close) < period + 5:
        return 0

    ema = close.ewm(span=period, adjust=False).mean()
    ema_slope = (ema.iloc[-1] - ema.iloc[-min(period, len(ema))]) / min(period, len(ema))

    price_ratio = close.iloc[-1] / ema.iloc[-1] - 1

    if ema_slope > 0.0005 and price_ratio > -0.01:
        return 1
    if ema_slope < -0.0005 and price_ratio < 0.01:
        return -1
    return 0


def bb_width_percentile(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
    lookback: int = 100,
) -> pd.Series:
    sma = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    width = (2 * std_dev * std) / sma.replace(0, np.nan)
    return width.rolling(lookback, min_periods=lookback).rank(pct=True) * 100


def hurst_exponent(series: pd.Series, max_lag: int = 50) -> float:
    values = series.dropna().values
    if len(values) < max_lag * 2:
        return 0.5

    max_lag = min(max_lag, len(values) // 2 - 1)
    if max_lag < 2:
        return 0.5

    lags = range(2, max_lag + 1)
    rs_values: list[float] = []

    for lag in lags:
        n_blocks = len(values) // lag
        if n_blocks < 1:
            continue
        blocks = values[: n_blocks * lag].reshape(n_blocks, lag)

        means = blocks.mean(axis=1, keepdims=True)
        deviations = blocks - means
        cumulative = deviations.cumsum(axis=1)

        rs: list[float] = []
        for i in range(n_blocks):
            r = cumulative[i].max() - cumulative[i].min()
            s = np.std(blocks[i], ddof=1)
            if s > 1e-12:
                rs.append(r / s)

        if rs:
            rs_values.append(float(np.mean(rs)))

    if len(rs_values) < 5:
        return 0.5

    log_lags = np.log(np.array(list(lags[: len(rs_values)]), dtype=float))
    log_rs = np.log(np.array(rs_values, dtype=float))

    coeffs = np.polyfit(log_lags, log_rs, 1)
    return float(coeffs[0])


def cusum_test(returns: pd.Series, threshold: float = 2.0) -> list[int]:
    if len(returns) < 2:
        return []

    arr = returns.dropna().values
    if len(arr) < 2:
        return []

    mean = arr.mean()
    std = arr.std(ddof=1)
    if std < 1e-12:
        return []

    standardized = (arr - mean) / std
    cumsum = 0.0
    change_points: list[int] = []

    for i in range(len(arr)):
        cumsum += standardized[i]
        if abs(cumsum) > threshold:
            change_points.append(i)
            cumsum = 0.0

    return change_points


def classify_regime(
    vol_percentile: float,
    adx: float,
    hurst: float,
    trend_dir: int,
) -> dict[str, str]:
    if any(pd.isna(v) for v in (vol_percentile, adx, hurst)):
        return {
            "volatility": "unknown",
            "trend_state": "unknown",
            "direction": "neutral",
            "mean_reversion": "unknown",
            "label": "UNKNOWN",
        }

    if vol_percentile < 33:
        volatility = "low"
    elif vol_percentile < 66:
        volatility = "medium"
    else:
        volatility = "high"

    if adx >= 25:
        trend_state = "trending"
    elif adx >= 15:
        trend_state = "transitional"
    else:
        trend_state = "ranging"

    direction = {1: "up", -1: "down"}.get(trend_dir, "neutral")

    if hurst < 0.4:
        mean_reversion = "strong"
    elif hurst < 0.5:
        mean_reversion = "weak"
    elif hurst < 0.6:
        mean_reversion = "none"
    else:
        mean_reversion = "trending"

    if trend_state == "trending" and direction != "neutral":
        label = f"TRENDING_{direction.upper()}"
    elif trend_state == "ranging":
        label = "RANGING"
    elif volatility == "high":
        label = "HIGH_VOL_RISK"
    else:
        label = "TRANSITIONAL"

    return {
        "volatility": volatility,
        "trend_state": trend_state,
        "direction": direction,
        "mean_reversion": mean_reversion,
        "label": label,
    }


class RegimeDetector:
    def detect(
        self,
        df: pd.DataFrame,
        volatility_lookback: int = 100,
    ) -> dict[str, Any]:
        required = {"high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        if df.empty or len(df) < 50:
            return self._empty_result()

        high = df["high"]
        low = df["low"]
        close = df["close"]

        atr_pct = atr_percentile(high, low, close, lookback=volatility_lookback)
        adx_series = compute_adx(high, low, close)
        bb_pct = bb_width_percentile(close, lookback=volatility_lookback)
        trend_dir = trend_direction(close)
        returns = close.pct_change().dropna()
        hurst = hurst_exponent(returns)

        vol_val = atr_pct.dropna()
        adx_val = adx_series.dropna()
        latest_vol = float(vol_val.iloc[-1]) if not vol_val.empty else 50.0
        latest_adx = float(adx_val.iloc[-1]) if not adx_val.empty else 20.0

        classification = classify_regime(latest_vol, latest_adx, hurst, trend_dir)
        change_points = cusum_test(returns)

        return {
            "regime_label": classification["label"],
            "vol_percentile": latest_vol,
            "adx": latest_adx,
            "hurst": hurst,
            "trend_dir": trend_dir,
            "classification": classification,
            "atr_percentile": atr_pct,
            "bb_width_pct": bb_pct,
            "change_points": change_points,
        }

    def strategy_from_regime(self, regime_info: dict[str, Any]) -> dict[str, Any]:
        classification = regime_info.get("classification", {})
        label = classification.get("label", "UNKNOWN")

        table: dict[str, dict[str, Any]] = {
            "TRENDING_UP": {
                "action": "BUY",
                "reason": "Strong uptrend — ride momentum",
                "position_sizing": 0.8,
            },
            "TRENDING_DOWN": {
                "action": "SELL",
                "reason": "Strong downtrend — reduce or short",
                "position_sizing": 0.0,
            },
            "RANGING": {
                "action": "HOLD",
                "reason": "Range-bound market — low conviction",
                "position_sizing": 0.3,
            },
            "HIGH_VOL_RISK": {
                "action": "REDUCE",
                "reason": "High volatility regime — reduce exposure",
                "position_sizing": 0.2,
            },
            "TRANSITIONAL": {
                "action": "WAIT",
                "reason": "Transitional market — wait for confirmation",
                "position_sizing": 0.3,
            },
            "INSUFFICIENT_DATA": {
                "action": "WAIT",
                "reason": "Insufficient data to determine regime",
                "position_sizing": 0.0,
            },
            "UNKNOWN": {
                "action": "WAIT",
                "reason": "Regime indeterminate — no action",
                "position_sizing": 0.0,
            },
        }

        return table.get(label, table["UNKNOWN"])

    def _empty_result(self) -> dict[str, Any]:
        unknown_cls = {
            "volatility": "unknown",
            "trend_state": "unknown",
            "direction": "neutral",
            "mean_reversion": "unknown",
            "label": "INSUFFICIENT_DATA",
        }
        return {
            "regime_label": "INSUFFICIENT_DATA",
            "vol_percentile": None,
            "adx": None,
            "hurst": None,
            "trend_dir": 0,
            "classification": unknown_cls,
            "atr_percentile": None,
            "bb_width_pct": None,
            "change_points": [],
        }
