"""Tests for AdvancedTechnicalAnalyzer"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def analyzer():
    from src.analysis.technical.advanced import AdvancedTechnicalAnalyzer

    return AdvancedTechnicalAnalyzer()


@pytest.fixture
def sample_df():
    dates = [date.today() - timedelta(days=i) for i in range(300, 0, -1)]
    close = 100.0
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {
                "date": d,
                "open": close,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": 1_000_000,
            }
        )
        close += (i % 10 - 5) * 0.5
    return pd.DataFrame(rows)


@pytest.fixture
def synthetic_ohlcv():
    rng = np.random.default_rng(42)
    n = 200
    dates = [date.today() - timedelta(days=i) for i in range(n, 0, -1)]
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 1, n))
    low = close - np.abs(rng.normal(0, 1, n))
    volume = rng.integers(500_000, 2_000_000, n)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - rng.normal(0, 0.5, n),
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


class TestIchimoku:
    def test_columns_added(self, analyzer, sample_df):
        result = analyzer.ichimoku(sample_df)
        expected = [
            "tenkan_sen",
            "kijun_sen",
            "senkou_span_a",
            "senkou_span_b",
            "chikou_span",
            "ichimoku_cloud_top",
            "ichimoku_cloud_bottom",
            "ichimoku_cloud_color",
            "ichimoku_above_cloud",
            "ichimoku_below_cloud",
            "ichimoku_tk_cross",
            "ichimoku_kk_cross",
        ]
        for col in expected:
            assert col in result.columns, f"Missing column: {col}"

    def test_tenkan_sen_calculation(self, analyzer, sample_df):
        result = analyzer.ichimoku(sample_df)
        expected = (
            sample_df["high"].rolling(9).max() + sample_df["low"].rolling(9).min()
        ) / 2
        pd.testing.assert_series_equal(
            result["tenkan_sen"], expected, check_names=False
        )

    def test_kijun_sen_calculation(self, analyzer, sample_df):
        result = analyzer.ichimoku(sample_df)
        expected = (
            sample_df["high"].rolling(26).max() + sample_df["low"].rolling(26).min()
        ) / 2
        pd.testing.assert_series_equal(
            result["kijun_sen"], expected, check_names=False
        )

    def test_chikou_span_shifted(self, analyzer, sample_df):
        result = analyzer.ichimoku(sample_df)
        expected = sample_df["close"].shift(-26)
        pd.testing.assert_series_equal(
            result["chikou_span"], expected, check_names=False
        )

    def test_tk_cross_bullish(self, analyzer):
        n = 100
        dates = [date.today() - timedelta(days=i) for i in range(n, 0, -1)]
        high = [100.0] * 70 + [120.0] * 30
        low = [90.0] * 70 + [115.0] * 30
        close = [(h + l) / 2 for h, l in zip(high, low)]
        df = pd.DataFrame(
            {
                "date": dates,
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000,
            }
        )
        result = analyzer.ichimoku(df)
        cross_vals = result["ichimoku_tk_cross"].dropna()
        assert len(cross_vals) > 0

    def test_senkou_span_a_shifted(self, analyzer, sample_df):
        result = analyzer.ichimoku(sample_df)
        tenkan = (
            sample_df["high"].rolling(9).max() + sample_df["low"].rolling(9).min()
        ) / 2
        kijun = (
            sample_df["high"].rolling(26).max() + sample_df["low"].rolling(26).min()
        ) / 2
        expected = ((tenkan + kijun) / 2).shift(26)
        pd.testing.assert_series_equal(
            result["senkou_span_a"], expected, check_names=False
        )

    def test_price_above_cloud(self, analyzer, sample_df):
        result = analyzer.ichimoku(sample_df)
        valid = result.dropna(subset=["ichimoku_cloud_top"])
        assert "ichimoku_above_cloud" in result.columns

    def test_empty_df(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.ichimoku(empty)
        assert result.empty

    def test_single_row(self, analyzer):
        single = pd.DataFrame(
            {
                "date": [date.today()],
                "open": [100.0],
                "high": [102.0],
                "low": [98.0],
                "close": [101.0],
                "volume": [1_000_000],
            }
        )
        result = analyzer.ichimoku(single)
        assert len(result) == 1


class TestFibonacciRetracement:
    def test_columns_added(self, analyzer, sample_df):
        result = analyzer.fibonacci_retracement(sample_df)
        for r in [0, 236, 382, 500, 618, 786, 1000, 1272, 1618]:
            assert f"fib_{r:04d}" in result.columns
        assert "fib_swing_low" in result.columns
        assert "fib_swing_high" in result.columns
        assert "fib_current_level" in result.columns

    def test_uptrend_levels(self, analyzer, sample_df):
        result = analyzer.fibonacci_retracement(sample_df, trend="up")
        high_val = result["fib_swing_high"].iloc[-1]
        low_val = result["fib_swing_low"].iloc[-1]
        assert high_val > low_val
        assert result["fib_1000"].iloc[-1] == low_val
        assert result["fib_0000"].iloc[-1] == high_val

    def test_downtrend_levels(self, analyzer, sample_df):
        result = analyzer.fibonacci_retracement(sample_df, trend="down")
        high_val = result["fib_swing_high"].iloc[-1]
        low_val = result["fib_swing_low"].iloc[-1]
        assert high_val > low_val

    def test_empty_df(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.fibonacci_retracement(empty)
        assert result.empty

    def test_single_row(self, analyzer):
        single = pd.DataFrame(
            {
                "date": [date.today()],
                "open": [100.0],
                "high": [102.0],
                "low": [98.0],
                "close": [101.0],
                "volume": [1_000_000],
            }
        )
        result = analyzer.fibonacci_retracement(single)
        assert len(result) == 1


class TestVolumeProfile:
    def test_columns_added(self, analyzer, sample_df):
        result = analyzer.volume_profile(sample_df)
        expected = [
            "volume_profile_poc",
            "volume_profile_va_high",
            "volume_profile_va_low",
            "volume_profile_poc_support",
            "volume_profile_poc_resistance",
        ]
        for col in expected:
            assert col in result.columns

    def test_poc_within_price_range(self, analyzer, sample_df):
        result = analyzer.volume_profile(sample_df)
        poc = result["volume_profile_poc"].iloc[-1]
        assert sample_df["low"].min() <= poc <= sample_df["high"].max()

    def test_va_bounds(self, analyzer, sample_df):
        result = analyzer.volume_profile(sample_df)
        assert (
            result["volume_profile_va_low"].iloc[-1]
            <= result["volume_profile_va_high"].iloc[-1]
        )

    def test_support_resistance_flags(self, analyzer, sample_df):
        result = analyzer.volume_profile(sample_df)
        assert result["volume_profile_poc_support"].dtype == bool
        assert result["volume_profile_poc_resistance"].dtype == bool

    def test_empty_df(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.volume_profile(empty)
        assert result.empty

    def test_single_row(self, analyzer):
        single = pd.DataFrame(
            {
                "date": [date.today()],
                "open": [100.0],
                "high": [102.0],
                "low": [98.0],
                "close": [101.0],
                "volume": [1_000_000],
            }
        )
        result = analyzer.volume_profile(single)
        assert len(result) == 1

    def test_constant_price(self, analyzer):
        const = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(50, 0, -1)],
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000_000,
            }
        )
        result = analyzer.volume_profile(const)
        assert not result["volume_profile_poc"].isna().all()


class TestMoneyFlowIndex:
    def test_columns_added(self, analyzer, sample_df):
        result = analyzer.money_flow_index(sample_df)
        assert "mfi" in result.columns

    def test_mfi_range(self, analyzer, synthetic_ohlcv):
        result = analyzer.money_flow_index(synthetic_ohlcv)
        mfi = result["mfi"].dropna()
        assert len(mfi) > 0
        assert mfi.between(0, 100).all()

    def test_mfi_upper_bound(self, analyzer):
        df = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(30, 0, -1)],
                "open": 100.0,
                "high": 102.0,
                "low": 98.0,
                "close": np.linspace(90, 110, 30),
                "volume": 1_000_000,
            }
        )
        result = analyzer.money_flow_index(df)
        assert "mfi" in result.columns

    def test_empty_df(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.money_flow_index(empty)
        assert result.empty

    def test_constant_prices(self, analyzer):
        const = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(20, 0, -1)],
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1_000_000,
            }
        )
        result = analyzer.money_flow_index(const)
        assert "mfi" in result.columns
        mfi = result["mfi"].dropna()
        assert ((mfi >= 0) & (mfi <= 100)).all()


class TestStochasticOscillator:
    def test_columns_added(self, analyzer, sample_df):
        result = analyzer.stochastic_oscillator(sample_df)
        assert "stoch_k" in result.columns
        assert "stoch_d" in result.columns

    def test_stoch_range(self, analyzer, synthetic_ohlcv):
        result = analyzer.stochastic_oscillator(synthetic_ohlcv)
        k = result["stoch_k"].dropna()
        d = result["stoch_d"].dropna()
        assert k.between(0, 100).all()
        assert d.between(0, 100).all()

    def test_stoch_k_extreme(self, analyzer):
        df = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(20, 0, -1)],
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": [100.0] * 19 + [50.0],
                "volume": 1_000_000,
            }
        )
        result = analyzer.stochastic_oscillator(df)
        k = result["stoch_k"].iloc[-1]
        assert 0 <= k <= 100

    def test_empty_df(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.stochastic_oscillator(empty)
        assert result.empty

    def test_single_row(self, analyzer):
        single = pd.DataFrame(
            {
                "date": [date.today()],
                "open": [100.0],
                "high": [102.0],
                "low": [98.0],
                "close": [101.0],
                "volume": [1_000_000],
            }
        )
        result = analyzer.stochastic_oscillator(single)
        assert "stoch_k" in result.columns


class TestOBV:
    def test_column_added(self, analyzer, sample_df):
        result = analyzer.obv(sample_df)
        assert "obv" in result.columns

    def test_obv_increases_on_up_close(self, analyzer):
        df = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(5, 0, -1)],
                "open": [100.0, 101.0, 102.0, 103.0, 104.0],
                "high": [102.0, 103.0, 104.0, 105.0, 106.0],
                "low": [98.0, 99.0, 100.0, 101.0, 102.0],
                "close": [101.0, 102.0, 103.0, 104.0, 105.0],
                "volume": [1000, 1000, 1000, 1000, 1000],
            }
        )
        result = analyzer.obv(df)
        assert result["obv"].is_monotonic_increasing

    def test_obv_decreases_on_down_close(self, analyzer):
        df = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(5, 0, -1)],
                "open": [105.0, 104.0, 103.0, 102.0, 101.0],
                "high": [106.0, 105.0, 104.0, 103.0, 102.0],
                "low": [104.0, 103.0, 102.0, 101.0, 100.0],
                "close": [104.0, 103.0, 102.0, 101.0, 100.0],
                "volume": [1000, 1000, 1000, 1000, 1000],
            }
        )
        result = analyzer.obv(df)
        assert result["obv"].is_monotonic_decreasing

    def test_empty_df(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.obv(empty)
        assert result.empty

    def test_missing_volume(self, analyzer):
        df = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(5, 0, -1)],
                "open": 100.0,
                "high": 102.0,
                "low": 98.0,
                "close": 101.0,
            }
        )
        with pytest.raises(KeyError):
            analyzer.obv(df)


class TestWilliamsR:
    def test_column_added(self, analyzer, sample_df):
        result = analyzer.williams_r(sample_df)
        assert "williams_r" in result.columns

    def test_williams_r_range(self, analyzer, synthetic_ohlcv):
        result = analyzer.williams_r(synthetic_ohlcv)
        wr = result["williams_r"].dropna()
        assert wr.between(-100, 0).all()

    def test_williams_r_extremes(self, analyzer):
        df = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(20, 0, -1)],
                "open": 100.0,
                "high": [100.0] * 19 + [100.0],
                "low": [100.0] * 19 + [100.0],
                "close": [100.0] * 19 + [100.0],
                "volume": 1_000_000,
            }
        )
        result = analyzer.williams_r(df)
        wr = result["williams_r"].dropna()
        assert ((wr >= -100) & (wr <= 0)).all()

    def test_empty_df(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.williams_r(empty)
        assert result.empty


class TestParabolicSAR:
    def test_column_added(self, analyzer, sample_df):
        result = analyzer.parabolic_sar(sample_df)
        assert "parabolic_sar" in result.columns

    def test_sar_values(self, analyzer, synthetic_ohlcv):
        result = analyzer.parabolic_sar(synthetic_ohlcv)
        sar = result["parabolic_sar"].dropna()
        assert len(sar) > 0
        assert sar.iloc[-1] > 0

    def test_sar_between_high_low(self, analyzer, synthetic_ohlcv):
        result = analyzer.parabolic_sar(synthetic_ohlcv)
        valid = result.dropna(subset=["parabolic_sar"])
        if len(valid) > 0:
            assert (valid["parabolic_sar"] >= valid["low"] * 0.5).all()
            assert (valid["parabolic_sar"] <= valid["high"] * 1.5).all()

    def test_empty_df(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.parabolic_sar(empty)
        assert result.empty

    def test_single_row(self, analyzer):
        single = pd.DataFrame(
            {
                "date": [date.today()],
                "open": [100.0],
                "high": [102.0],
                "low": [98.0],
                "close": [101.0],
                "volume": [1_000_000],
            }
        )
        result = analyzer.parabolic_sar(single)
        assert len(result) == 1


class TestComputeAllAdvanced:
    def test_returns_dataframe(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert isinstance(result, pd.DataFrame)

    def test_adds_ichimoku_columns(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert "tenkan_sen" in result.columns
        assert "kijun_sen" in result.columns

    def test_adds_fibonacci_columns(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert "fib_0618" in result.columns
        assert "fib_swing_low" in result.columns

    def test_adds_volume_profile_columns(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert "volume_profile_poc" in result.columns
        assert "volume_profile_va_high" in result.columns

    def test_adds_mfi_column(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert "mfi" in result.columns

    def test_adds_stochastic_columns(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert "stoch_k" in result.columns
        assert "stoch_d" in result.columns

    def test_adds_obv_column(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert "obv" in result.columns

    def test_adds_williams_r_column(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert "williams_r" in result.columns

    def test_adds_parabolic_sar_column(self, analyzer, sample_df):
        result = analyzer.compute_all_advanced(sample_df)
        assert "parabolic_sar" in result.columns

    def test_empty_df_returns_empty(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.compute_all_advanced(empty)
        assert result.empty

    def test_sorts_by_date(self, analyzer):
        import random

        dates = [date.today() - timedelta(days=i) for i in range(100)]
        shuffled = list(dates)
        random.shuffle(shuffled)
        df = pd.DataFrame(
            [
                {
                    "date": d,
                    "close": 100.0,
                    "open": 99.0,
                    "high": 101.0,
                    "low": 98.0,
                    "volume": 1000,
                }
                for d in shuffled
            ]
        )
        result = analyzer.compute_all_advanced(df)
        assert result["date"].is_monotonic_increasing


class TestVolumeProfileEdgeCases:
    def test_poc_identification(self, analyzer):
        n = 100
        dates = [date.today() - timedelta(days=i) for i in range(n, 0, -1)]
        prices = np.concatenate(
            [np.linspace(90, 110, 50), np.full(50, 110.0)]
        )
        df = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": prices + 1,
                "low": prices - 1,
                "close": prices,
                "volume": np.where(prices >= 110, 5_000_000, 100_000),
            }
        )
        result = analyzer.volume_profile(df)
        poc = result["volume_profile_poc"].iloc[-1]
        assert poc >= 105

    def test_missing_volume_column(self, analyzer):
        df = pd.DataFrame(
            {
                "date": [date.today() - timedelta(days=i) for i in range(5, 0, -1)],
                "open": 100.0,
                "high": 102.0,
                "low": 98.0,
                "close": 101.0,
            }
        )
        with pytest.raises((KeyError, AttributeError)):
            analyzer.volume_profile(df)


class TestExport:
    def test_advanced_analyzer_exported(self):
        from src.analysis.technical import AdvancedTechnicalAnalyzer

        assert AdvancedTechnicalAnalyzer is not None
