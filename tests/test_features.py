from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from src.analysis.market.features import (
    FeatureBuilder,
    _adf_pvalue,
    _bollinger_bands,
    _build_adf_design,
    _forward_return,
    abs_return,
    adf_test,
    bb_position,
    bb_width,
    binary_labels,
    close_position,
    correlation_filter,
    dollar_volume,
    high_low_range,
    log_return,
    low_variance_filter,
    momentum,
    multiclass_labels,
    obv_slope,
    regression_target,
    return_volatility,
    rolling_kurtosis,
    rolling_minmax,
    rolling_rank,
    rolling_skew,
    rolling_zscore,
    volume_ma_ratio,
    volume_ratio,
    vwap_deviation,
)


def _price_series(n=100, seed=42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100 + np.cumsum(rng.normal(0, 0.5, n)))


def _ohlcv_df(n=100, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    volume = np.abs(rng.integers(1000, 10000, n))
    open_ = close - rng.normal(0, 0.2, n)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


class TestPriceFeatures:
    def test_log_return(self):
        close = _price_series()
        result = log_return(close)
        assert np.isnan(result.iloc[0])
        assert result.dropna().between(-1, 1).all()

    def test_abs_return(self):
        close = _price_series()
        result = abs_return(close)
        assert np.isnan(result.iloc[0])
        assert (result.dropna() >= 0).all()

    def test_return_volatility(self):
        close = _price_series()
        result = return_volatility(close, window=20)
        assert result.dropna().between(0, 1).all()

    def test_momentum_positive_for_up_trend(self):
        close = pd.Series(np.linspace(100, 120, 30))
        mom = momentum(close, window=5)
        assert mom.dropna().iloc[-1] > 0

    def test_momentum_negative_for_down_trend(self):
        close = pd.Series(np.linspace(120, 100, 30))
        mom = momentum(close, window=5)
        assert mom.dropna().iloc[-1] < 0

    def test_high_low_range(self):
        high = pd.Series([10, 12, 15])
        low = pd.Series([8, 9, 10])
        close = pd.Series([9, 11, 14])
        result = high_low_range(high, low, close)
        assert (result > 0).all()

    def test_close_position(self):
        high = pd.Series([10, 12, 15])
        low = pd.Series([8, 9, 10])
        close = pd.Series([9, 11, 14])
        result = close_position(high, low, close)
        assert result.between(0, 1).all()

    def test_rolling_skew(self):
        close = _price_series()
        result = rolling_skew(close, window=20)
        assert len(result) == 100

    def test_rolling_kurtosis(self):
        close = _price_series()
        result = rolling_kurtosis(close, window=20)
        assert len(result) == 100


class TestVolumeFeatures:
    def test_volume_ratio(self):
        volume = pd.Series(np.abs(np.random.default_rng(42).integers(1000, 10000, 50)))
        result = volume_ratio(volume, window=20)
        assert result.dropna().min() >= 0

    def test_volume_ma_ratio(self):
        volume = pd.Series(np.abs(np.random.default_rng(42).integers(1000, 10000, 50)))
        result = volume_ma_ratio(volume)
        assert len(result) == 50

    def test_obv_slope(self):
        close = _price_series(50)
        volume = pd.Series(np.abs(np.random.default_rng(42).integers(1000, 10000, 50)))
        result = obv_slope(close, volume, window=10)
        assert len(result) == 50

    def test_vwap_deviation(self):
        df = _ohlcv_df(50)
        result = vwap_deviation(df["high"], df["low"], df["close"], df["volume"])
        assert len(result) == 50

    def test_dollar_volume(self):
        result = dollar_volume(
            pd.Series([100.0, 101.0]),
            pd.Series([1000, 2000]),
        )
        assert result.iloc[0] == 100_000.0
        assert result.iloc[1] == 202_000.0


class TestTechnicalFeatures:
    def test_bollinger_bands_upper_above_lower(self):
        close = _price_series()
        upper, mid, lower = _bollinger_bands(close)
        assert (upper.dropna() >= mid.dropna()).all()
        assert (mid.dropna() >= lower.dropna()).all()

    def test_bb_position(self):
        close = _price_series()
        result = bb_position(close)
        assert result.dropna().notna().any()
        assert np.isfinite(result.dropna()).all()

    def test_bb_width(self):
        close = _price_series()
        result = bb_width(close)
        assert (result.dropna() >= 0).all()


class TestStationarity:
    def test_adf_test_returns_tuple(self):
        rng = np.random.default_rng(42)
        series = pd.Series(np.cumsum(rng.normal(0, 1, 300)))
        result = adf_test(series, autolag=True)
        assert len(result) == 3
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)
        assert isinstance(result[2], bool)

    def test_adf_test_short_series_returns_nan(self):
        series = pd.Series([1, 2, 3])
        t_stat, p_value, stationary = adf_test(series)
        assert np.isnan(t_stat)
        assert np.isnan(p_value)
        assert stationary is False

    def test_adf_pvalue_extremes(self):
        assert _adf_pvalue(-10.0, 100) == 0.001
        assert _adf_pvalue(10.0, 100) == 0.50

    def test_adf_pvalue_uses_interpolation(self):
        p = _adf_pvalue(-2.5, 300)
        assert isinstance(p, float)

    def test_build_adf_design(self):
        y_lag = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        dy = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
        x = _build_adf_design(y_lag, dy, lag=1)
        assert x.shape[1] == 3  # const, y_lag, lag1
        assert x.shape[0] == 4  # n - lag = 5 - 1


class TestNormalization:
    def test_rolling_zscore(self):
        series = _price_series()
        result = rolling_zscore(series, window=60)
        assert len(result) == 100

    def test_rolling_minmax(self):
        series = _price_series()
        result = rolling_minmax(series, window=60)
        assert len(result) == 100
        assert result.dropna().notna().any()

    def test_rolling_rank(self):
        series = _price_series()
        result = rolling_rank(series, window=60)
        assert result.dropna().between(0, 1).all()


class TestFeatureSelection:
    def test_correlation_filter_removes_highly_correlated(self):
        df = pd.DataFrame({
            "a": [1, 2, 3, 4, 5],
            "b": [2, 4, 6, 8, 10],
            "c": [5, 4, 3, 2, 1],
        })
        result = correlation_filter(df, threshold=0.9)
        assert "a" in result.columns or "b" in result.columns
        assert not ({"a", "b"}.issubset(set(result.columns)))

    def test_correlation_filter_empty(self):
        assert correlation_filter(pd.DataFrame()).empty

    def test_low_variance_filter_removes_constant(self):
        df = pd.DataFrame({
            "a": [1, 1, 1, 1],
            "b": [1, 2, 3, 4],
        })
        result = low_variance_filter(df, threshold=0.1)
        assert "a" not in result.columns
        assert "b" in result.columns

    def test_low_variance_filter_empty(self):
        assert low_variance_filter(pd.DataFrame()).empty


class TestLabelCreation:
    def test_forward_return(self):
        close = pd.Series([100, 102, 104, 106, 108])
        result = _forward_return(close, forward_period=1)
        assert result.iloc[0] == pytest.approx(0.02, rel=1e-3)
        assert np.isnan(result.iloc[-1])

    def test_binary_labels(self):
        close = pd.Series([100, 100, 101.5, 99, 102])
        labels = binary_labels(close, forward_period=1, threshold=0.01)
        assert labels.dtype == np.int64

    def test_multiclass_labels(self):
        close = pd.Series([100, 100, 101.5, 99, 102])
        labels = multiclass_labels(close, forward_period=1, threshold=0.01)
        assert set(labels.dropna().unique()).issubset({0, 1, 2})

    def test_regression_target(self):
        close = pd.Series([100, 102, 104])
        target = regression_target(close, forward_period=1)
        assert target.iloc[0] == pytest.approx(0.02, rel=1e-3)
        assert np.isnan(target.iloc[-1])


class TestFeatureBuilder:
    def test_build_all_features(self):
        df = _ohlcv_df(100)
        builder = FeatureBuilder()
        features = builder.build(df)
        assert "log_return" in features.columns
        assert "momentum_5" in features.columns
        assert "volume_ratio_20" in features.columns
        assert "bb_position" in features.columns
        assert "rolling_zscore_60" in features.columns
        assert len(features) == 100

    def test_build_selected_group(self):
        df = _ohlcv_df(100)
        builder = FeatureBuilder(config={"price": True, "volume": False, "technical": False, "normalization": False})
        features = builder.build(df)
        assert "log_return" in features.columns
        assert "volume_ratio_20" not in features.columns

    def test_build_raises_on_missing_columns(self):
        builder = FeatureBuilder()
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match="Missing required columns"):
            builder.build(df)

    def test_build_disabled_group_skipped(self):
        df = _ohlcv_df(100)
        builder = FeatureBuilder(config={"price": False, "volume": False, "technical": False, "normalization": False})
        features = builder.build(df)
        assert features.empty

    def test_default_config_enables_all(self):
        builder = FeatureBuilder()
        assert builder.config["price"] is True
        assert builder.config["volume"] is True
        assert builder.config["technical"] is True
        assert builder.config["normalization"] is True

    def test_build_preserves_index(self):
        df = _ohlcv_df(100)
        builder = FeatureBuilder()
        features = builder.build(df)
        assert (features.index == df.index).all()
