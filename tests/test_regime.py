from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from src.analysis.market.regime import (
    RegimeDetector,
    atr_percentile,
    bb_width_percentile,
    classify_regime,
    compute_adx,
    cusum_test,
    hurst_exponent,
    trend_direction,
)


def _make_ohlc_df(n=200, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    return pd.DataFrame({"high": high, "low": low, "close": close})


class TestTrueRange:
    def test_basic_calculation(self):
        df = _make_ohlc_df(50)
        from src.analysis.market.regime import _true_range
        tr = _true_range(df["high"], df["low"], df["close"])
        assert len(tr) == 50
        assert tr.iloc[0] == df["high"].iloc[0] - df["low"].iloc[0]
        assert tr.min() >= 0

    def test_first_value_is_hl(self):
        high = pd.Series([10, 12, 15])
        low = pd.Series([8, 9, 10])
        close = pd.Series([9, 11, 14])
        from src.analysis.market.regime import _true_range
        tr = _true_range(high, low, close)
        assert tr.iloc[0] == 2.0


class TestATRPercentile:
    def test_returns_percentile_values(self):
        df = _make_ohlc_df(200)
        result = atr_percentile(df["high"], df["low"], df["close"])
        assert len(result) == 200
        assert result.dropna().between(0, 100).all()

    def test_early_values_are_nan(self):
        df = _make_ohlc_df(50)
        result = atr_percentile(df["high"], df["low"], df["close"], lookback=100)
        assert result.iloc[:50].isna().all()

    def test_increasing_volatility_ranks_higher(self):
        rng = np.random.default_rng(42)
        arr = 100 + np.cumsum(rng.normal(0, 0.1, 300))
        close = pd.Series(arr)
        high = pd.Series(arr + np.abs(rng.normal(0, 0.2, 300)))
        low = pd.Series(arr - np.abs(rng.normal(0, 0.2, 300)))
        high.iloc[-100:] *= 1.5
        low.iloc[-100:] *= 0.7
        result = atr_percentile(high, low, close, lookback=150)
        tail = result.dropna().iloc[-20:]
        assert tail.mean() > 60


class TestComputeADX:
    def test_adx_between_0_and_100(self):
        df = _make_ohlc_df(200)
        adx = compute_adx(df["high"], df["low"], df["close"])
        assert len(adx) == 200
        tail = adx.dropna()
        assert tail.between(0, 100).all()

    def test_trending_market_gives_higher_adx(self):
        close = pd.Series(np.linspace(100, 130, 200) + np.random.normal(0, 0.3, 200))
        high = close + 0.5
        low = close - 0.5
        adx = compute_adx(high, low, close, period=14)
        val = adx.dropna().iloc[-1]
        assert val > 20

    def test_choppy_market_gives_low_adx(self):
        rng = np.random.default_rng(42)
        close = pd.Series(100 + rng.normal(0, 0.3, 200))
        high = close + 0.5
        low = close - 0.5
        adx = compute_adx(high, low, close, period=14)
        val = adx.dropna().iloc[-1]
        assert val < 30


class TestTrendDirection:
    def test_uptrend_returns_1(self):
        close = pd.Series(np.linspace(100, 130, 50))
        assert trend_direction(close) == 1

    def test_downtrend_returns_minus_1(self):
        close = pd.Series(np.linspace(130, 100, 50))
        assert trend_direction(close) == -1

    def test_no_trend_returns_0(self):
        close = pd.Series(np.full(80, 100.0))
        assert trend_direction(close) == 0

    def test_insufficient_data_returns_0(self):
        close = pd.Series([100, 101, 102])
        assert trend_direction(close) == 0


class TestBBWidthPercentile:
    def test_returns_percentile_0_to_100(self):
        df = _make_ohlc_df(200)
        result = bb_width_percentile(df["close"])
        assert len(result) == 200
        assert result.dropna().between(0, 100).all()

    def test_narrowing_bands_rank_lower(self):
        n = 300
        decay = np.exp(-np.linspace(0, 3, n))
        rng = np.random.default_rng(42)
        close = pd.Series(100 + np.cumsum(rng.normal(0, 1.0, n) * decay))
        bw = bb_width_percentile(close, period=20, lookback=150)
        first_third = bw.dropna().iloc[:30].mean()
        last_third = bw.dropna().iloc[-30:].mean()
        assert last_third < first_third


class TestHurstExponent:
    def test_returns_float(self):
        rng = np.random.default_rng(42)
        series = pd.Series(np.cumsum(rng.normal(0, 1, 1000)))
        h = hurst_exponent(series)
        assert isinstance(h, float)

    def test_too_short_series_returns_0_5(self):
        assert hurst_exponent(pd.Series([1, 2, 3]), max_lag=10) == 0.5

    def test_constant_series_returns_0_5(self):
        assert hurst_exponent(pd.Series(np.ones(200)), max_lag=50) == 0.5

    def test_max_lag_too_small_returns_0_5(self):
        series = pd.Series(np.random.default_rng(42).normal(0, 1, 10))
        assert hurst_exponent(series, max_lag=10) == 0.5


class TestCUSUM:
    def test_returns_change_points(self):
        returns = pd.Series(np.random.normal(0, 0.5, 200))
        points = cusum_test(returns, threshold=2.0)
        assert isinstance(points, list)

    def test_returns_empty_for_too_short(self):
        assert cusum_test(pd.Series([0.01])) == []

    def test_returns_empty_for_constant_returns(self):
        assert cusum_test(pd.Series(np.zeros(100))) == []

    def test_detects_shifts(self):
        rng = np.random.default_rng(42)
        returns = pd.Series(np.concatenate([rng.normal(0, 0.3, 100), rng.normal(2, 0.3, 100)]))
        points = cusum_test(returns, threshold=1.5)
        assert any(p >= 95 for p in points)


class TestClassifyRegime:
    def test_unknown_on_nan(self):
        result = classify_regime(np.nan, 25, 0.5, 1)
        assert result["label"] == "UNKNOWN"

    def test_trending_up(self):
        result = classify_regime(50, 30, 0.6, 1)
        assert result["label"] == "TRENDING_UP"
        assert result["trend_state"] == "trending"
        assert result["direction"] == "up"

    def test_trending_down(self):
        result = classify_regime(50, 30, 0.6, -1)
        assert result["label"] == "TRENDING_DOWN"
        assert result["direction"] == "down"

    def test_ranging_low_adx(self):
        result = classify_regime(50, 10, 0.5, 0)
        assert result["label"] == "RANGING"
        assert result["trend_state"] == "ranging"

    def test_high_vol_risk(self):
        result = classify_regime(80, 20, 0.5, 0)
        assert result["label"] == "HIGH_VOL_RISK"
        assert result["volatility"] == "high"
        assert result["trend_state"] == "transitional"

    def test_transitional(self):
        result = classify_regime(50, 20, 0.5, 0)
        assert result["label"] == "TRANSITIONAL"
        assert result["trend_state"] == "transitional"

    def test_mean_reversion_strong(self):
        result = classify_regime(50, 10, 0.3, 0)
        assert result["mean_reversion"] == "strong"

    def test_mean_reversion_trending(self):
        result = classify_regime(50, 10, 0.7, 0)
        assert result["mean_reversion"] == "trending"

    def test_volatility_thresholds(self):
        assert classify_regime(10, 10, 0.5, 0)["volatility"] == "low"
        assert classify_regime(50, 10, 0.5, 0)["volatility"] == "medium"
        assert classify_regime(80, 10, 0.5, 0)["volatility"] == "high"


class TestRegimeDetector:
    def test_detect_returns_dict_with_keys(self):
        detector = RegimeDetector()
        df = _make_ohlc_df(200)
        result = detector.detect(df)
        assert "regime_label" in result
        assert "vol_percentile" in result
        assert "adx" in result
        assert "hurst" in result
        assert "classification" in result
        assert "change_points" in result

    def test_detect_raises_on_missing_columns(self):
        detector = RegimeDetector()
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match="Missing columns"):
            detector.detect(df)

    def test_detect_empty_dataframe(self):
        detector = RegimeDetector()
        df = pd.DataFrame({"high": [], "low": [], "close": []})
        result = detector.detect(df)
        assert result["regime_label"] == "INSUFFICIENT_DATA"

    def test_detect_too_few_rows(self):
        detector = RegimeDetector()
        df = pd.DataFrame({"high": [1, 2], "low": [1, 2], "close": [1, 2]})
        result = detector.detect(df)
        assert result["regime_label"] == "INSUFFICIENT_DATA"

    def test_strategy_from_regime_trending_up(self):
        detector = RegimeDetector()
        result = detector.strategy_from_regime(
            {"classification": {"label": "TRENDING_UP"}}
        )
        assert result["action"] == "BUY"
        assert result["position_sizing"] == 0.8

    def test_strategy_from_regime_trending_down(self):
        detector = RegimeDetector()
        result = detector.strategy_from_regime(
            {"classification": {"label": "TRENDING_DOWN"}}
        )
        assert result["action"] == "SELL"
        assert result["position_sizing"] == 0.0

    def test_strategy_from_regime_ranging(self):
        detector = RegimeDetector()
        result = detector.strategy_from_regime(
            {"classification": {"label": "RANGING"}}
        )
        assert result["action"] == "HOLD"

    def test_strategy_from_regime_unknown(self):
        detector = RegimeDetector()
        result = detector.strategy_from_regime({})
        assert result["action"] == "WAIT"

    def test_empty_result_structure(self):
        detector = RegimeDetector()
        result = detector._empty_result()
        assert result["regime_label"] == "INSUFFICIENT_DATA"
        assert result["change_points"] == []
        assert result["classification"]["label"] == "INSUFFICIENT_DATA"

    def test_integration_trending_up_smoke(self):
        rng = np.random.default_rng(42)
        close = pd.Series(np.linspace(100, 140, 250) + rng.normal(0, 0.5, 250))
        high = close + np.abs(rng.normal(0, 0.3, 250))
        low = close - np.abs(rng.normal(0, 0.3, 250))
        df = pd.DataFrame({"high": high, "low": low, "close": close})
        detector = RegimeDetector()
        result = detector.detect(df)
        assert result["trend_dir"] in (1, 0, -1)
