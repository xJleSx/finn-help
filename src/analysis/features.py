from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Price Features
# ──────────────────────────────────────────────


def log_return(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def abs_return(close: pd.Series) -> pd.Series:
    return log_return(close).abs()


def return_volatility(close: pd.Series, window: int = 20) -> pd.Series:
    return log_return(close).rolling(window=window).std()


def momentum(close: pd.Series, window: int = 5) -> pd.Series:
    return close / close.shift(window) - 1


def high_low_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    return (high - low) / close


def close_position(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    denom = high - low
    return (close - low) / denom.replace(0, np.nan)


def rolling_skew(close: pd.Series, window: int = 20) -> pd.Series:
    return log_return(close).rolling(window=window).skew()


def rolling_kurtosis(close: pd.Series, window: int = 20) -> pd.Series:
    return log_return(close).rolling(window=window).kurt()


# ──────────────────────────────────────────────
# Volume Features
# ──────────────────────────────────────────────


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    return volume / volume.rolling(window=window).mean()


def volume_ma_ratio(
    volume: pd.Series, short_window: int = 5, long_window: int = 20
) -> pd.Series:
    short_ma = volume.rolling(window=short_window).mean()
    long_ma = volume.rolling(window=long_window).mean()
    return short_ma / long_ma.replace(0, np.nan)


def obv_slope(close: pd.Series, volume: pd.Series, window: int = 10) -> pd.Series:
    obv = (volume * (close.diff() > 0).map({True: 1, False: -1})).fillna(0).cumsum()

    def _slope(y: pd.Series) -> float:
        x = np.arange(len(y))
        mask = y.notna()
        if mask.sum() < 2:
            return np.nan
        slope, _ = np.polyfit(x[mask], y[mask], 1)
        return slope

    return obv.rolling(window=window).apply(_slope, raw=False)


def vwap_deviation(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
) -> pd.Series:
    typical = (high + low + close) / 3
    vwap = (typical * volume).cumsum() / volume.cumsum().replace(0, np.nan)
    return (close - vwap) / vwap.replace(0, np.nan)


def dollar_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    return close * volume


# ──────────────────────────────────────────────
# Technical Features (wrappers)
# ──────────────────────────────────────────────


def _bollinger_bands(
    close: pd.Series, window: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(window=window).mean()
    std = close.rolling(window=window).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def bb_position(
    close: pd.Series, window: int = 20, std_dev: float = 2.0
) -> pd.Series:
    upper, _, lower = _bollinger_bands(close, window, std_dev)
    denom = upper - lower
    return (close - lower) / denom.replace(0, np.nan)


def bb_width(
    close: pd.Series, window: int = 20, std_dev: float = 2.0
) -> pd.Series:
    upper, mid, lower = _bollinger_bands(close, window, std_dev)
    return (upper - lower) / mid.replace(0, np.nan)


# ──────────────────────────────────────────────
# Stationarity
# ──────────────────────────────────────────────


def adf_test(
    series: pd.Series, maxlag: int | None = None, autolag: bool = True
) -> tuple[float, float, bool]:
    series = series.dropna().values.astype(float)
    n = len(series)
    if n < 10:
        return (np.nan, np.nan, False)

    dy = np.diff(series)
    y_lag = series[:-1]

    n_obs = len(dy)
    if maxlag is None:
        maxlag = int(np.floor(12 * (n_obs / 100) ** 0.25))
    maxlag = min(maxlag, n_obs - 2)

    if autolag:
        best_aic = np.inf
        best_lag = 0
        for k in range(maxlag + 1):
            X = _build_adf_design(y_lag, dy, k)
            try:
                beta, res, rank, sv = np.linalg.lstsq(X, dy, rcond=None)
                resid = dy - X @ beta
                sigma2 = resid @ resid / n_obs
                aic = n_obs * np.log(sigma2) + 2 * (k + 2)
                if aic < best_aic:
                    best_aic = aic
                    best_lag = k
            except np.linalg.LinAlgError:
                continue
        lag = best_lag
    else:
        lag = maxlag

    X = _build_adf_design(y_lag, dy, lag)
    try:
        beta, res, rank, sv = np.linalg.lstsq(X, dy, rcond=None)
    except np.linalg.LinAlgError:
        return (np.nan, np.nan, False)

    resid = dy - X @ beta
    n_params = X.shape[1]
    dof = n_obs - n_params
    if dof < 1:
        return (np.nan, np.nan, False)
    mse = resid @ resid / dof
    se = np.sqrt(mse * np.linalg.inv(X.T @ X).diagonal())
    t_stat = beta[0] / se[0] if se[0] > 0 else np.nan

    p_value = _adf_pvalue(t_stat, n_obs)
    return (float(t_stat), float(p_value), bool(p_value < 0.05))


def _build_adf_design(y_lag: np.ndarray, dy: np.ndarray, lag: int) -> np.ndarray:
    n = len(dy)
    cols = [y_lag]
    if lag > 0:
        for k in range(lag):
            cols.append(np.concatenate([np.zeros(k + 1), dy[:n - k - 1]]))
    X = np.column_stack(cols)
    X = np.column_stack([np.ones(X.shape[0]), X])
    return X[lag:]


def _adf_pvalue(t_stat: float, n: int) -> float:
    tau = np.array([-3.43, -2.86, -2.57, -2.28, -1.95])
    probs = np.array([0.01, 0.05, 0.10, 0.20, 0.50])
    if t_stat <= tau[0]:
        return 0.001
    if t_stat >= tau[-1]:
        return 0.50
    if n < 25:
        n_idx = 0
    elif n < 50:
        n_idx = 1
    elif n < 100:
        n_idx = 2
    elif n < 250:
        n_idx = 3
    else:
        n_idx = 4
    tau_n = tau
    return float(np.interp(t_stat, tau_n[::-1], probs[::-1]))


# ──────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────


def rolling_zscore(series: pd.Series, window: int = 60) -> pd.Series:
    mean = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    return (series - mean) / std.replace(0, np.nan)


def rolling_minmax(series: pd.Series, window: int = 60) -> pd.Series:
    min_val = series.rolling(window=window).min()
    max_val = series.rolling(window=window).max()
    denom = max_val - min_val
    return (series - min_val) / denom.replace(0, np.nan)


def rolling_rank(series: pd.Series, window: int = 60) -> pd.Series:
    return series.rolling(window=window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )


# ──────────────────────────────────────────────
# Feature Selection
# ──────────────────────────────────────────────


def correlation_filter(df: pd.DataFrame, threshold: float = 0.9) -> pd.DataFrame:
    if df.empty:
        return df
    corr = df.corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    to_drop = {col for col in upper.columns if any(upper[col] > threshold)}
    return df.drop(columns=to_drop)


def low_variance_filter(df: pd.DataFrame, threshold: float = 0.01) -> pd.DataFrame:
    if df.empty:
        return df
    variances = df.var()
    keep = variances[variances >= threshold].index
    return df[keep]


# ──────────────────────────────────────────────
# Label Creation
# ──────────────────────────────────────────────


def _forward_return(close: pd.Series, forward_period: int = 1) -> pd.Series:
    return close.shift(-forward_period) / close - 1


def binary_labels(
    close: pd.Series, forward_period: int = 1, threshold: float = 0.01
) -> pd.Series:
    fwd_ret = _forward_return(close, forward_period)
    return (fwd_ret > threshold).astype(int)


def multiclass_labels(
    close: pd.Series, forward_period: int = 1, threshold: float = 0.01
) -> pd.Series:
    fwd_ret = _forward_return(close, forward_period)
    labels = pd.Series(1, index=close.index)
    labels[fwd_ret < -threshold] = 0
    labels[fwd_ret > threshold] = 2
    labels[fwd_ret.isna()] = np.nan
    return labels


def regression_target(
    close: pd.Series, forward_period: int = 1
) -> pd.Series:
    return _forward_return(close, forward_period)


# ──────────────────────────────────────────────
# FeatureBuilder
# ──────────────────────────────────────────────


class FeatureBuilder:
    REQUIRED_COLS = {"open", "high", "low", "close", "volume"}

    FEATURE_REGISTRY: dict[str, list[dict[str, Any]]] = {
        "price": [
            {"name": "log_return", "fn": lambda df: log_return(df["close"]).rename("log_return")},
            {"name": "abs_return", "fn": lambda df: abs_return(df["close"]).rename("abs_return")},
            {"name": "return_volatility_20", "fn": lambda df: return_volatility(df["close"], 20).rename("return_volatility_20")},
            {"name": "momentum_5", "fn": lambda df: momentum(df["close"], 5).rename("momentum_5")},
            {"name": "high_low_range", "fn": lambda df: high_low_range(df["high"], df["low"], df["close"]).rename("high_low_range")},
            {"name": "close_position", "fn": lambda df: close_position(df["high"], df["low"], df["close"]).rename("close_position")},
            {"name": "rolling_skew_20", "fn": lambda df: rolling_skew(df["close"], 20).rename("rolling_skew_20")},
            {"name": "rolling_kurtosis_20", "fn": lambda df: rolling_kurtosis(df["close"], 20).rename("rolling_kurtosis_20")},
        ],
        "volume": [
            {"name": "volume_ratio_20", "fn": lambda df: volume_ratio(df["volume"], 20).rename("volume_ratio_20")},
            {"name": "volume_ma_ratio", "fn": lambda df: volume_ma_ratio(df["volume"], 5, 20).rename("volume_ma_ratio")},
            {"name": "obv_slope_10", "fn": lambda df: obv_slope(df["close"], df["volume"], 10).rename("obv_slope_10")},
            {"name": "vwap_deviation", "fn": lambda df: vwap_deviation(df["high"], df["low"], df["close"], df["volume"]).rename("vwap_deviation")},
            {"name": "dollar_volume", "fn": lambda df: dollar_volume(df["close"], df["volume"]).rename("dollar_volume")},
        ],
        "technical": [
            {"name": "bb_position", "fn": lambda df: bb_position(df["close"]).rename("bb_position")},
            {"name": "bb_width", "fn": lambda df: bb_width(df["close"]).rename("bb_width")},
        ],
        "normalization": [
            {"name": "rolling_zscore_60", "fn": lambda df: rolling_zscore(df["close"], 60).rename("rolling_zscore_60")},
            {"name": "rolling_minmax_60", "fn": lambda df: rolling_minmax(df["close"], 60).rename("rolling_minmax_60")},
            {"name": "rolling_rank_60", "fn": lambda df: rolling_rank(df["close"], 60).rename("rolling_rank_60")},
        ],
    }

    def __init__(self, config: dict[str, Any] | None = None):
        if config is None:
            config = {group: True for group in self.FEATURE_REGISTRY}
        self.config = config

    def build(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = self.REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        df = df.sort_index().copy()
        features = pd.DataFrame(index=df.index)

        for group_name, feature_list in self.FEATURE_REGISTRY.items():
            if not self.config.get(group_name, False):
                continue
            for feat in feature_list:
                try:
                    result = feat["fn"](df)
                    features[result.name] = result
                except Exception as exc:
                    logger.warning("Failed to compute feature '%s': %s", feat["name"], exc)

        return features
