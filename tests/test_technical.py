"""Tests for TechnicalAnalyzer"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest


@pytest.fixture
def analyzer():
    from src.analysis.technical import TechnicalAnalyzer
    return TechnicalAnalyzer()


@pytest.fixture
def sample_df():
    dates = [date.today() - timedelta(days=i) for i in range(200, 0, -1)]
    close = 100.0
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "date": d,
            "open": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": 1_000_000,
        })
        close += (i % 10 - 5) * 0.5
    return pd.DataFrame(rows)


class TestComputeAll:
    def test_returns_dataframe(self, analyzer, sample_df):
        result = analyzer.compute_all(sample_df)
        assert isinstance(result, pd.DataFrame)

    def test_adds_rsi_column(self, analyzer, sample_df):
        result = analyzer.compute_all(sample_df)
        assert "rsi" in result.columns

    def test_adds_macd_columns(self, analyzer, sample_df):
        result = analyzer.compute_all(sample_df)
        assert "macd_line" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_hist" in result.columns

    def test_adds_sma_columns(self, analyzer, sample_df):
        result = analyzer.compute_all(sample_df)
        for period in [20, 50, 200]:
            assert f"sma_{period}" in result.columns

    def test_adds_bb_columns(self, analyzer, sample_df):
        result = analyzer.compute_all(sample_df)
        assert "bb_upper" in result.columns
        assert "bb_lower" in result.columns
        assert "bb_mid" in result.columns

    def test_adds_atr_column(self, analyzer, sample_df):
        result = analyzer.compute_all(sample_df)
        assert "atr" in result.columns

    def test_adds_volume_sma(self, analyzer, sample_df):
        result = analyzer.compute_all(sample_df)
        assert "volume_sma_20" in result.columns

    def test_empty_df_returns_empty(self, analyzer):
        empty = pd.DataFrame()
        result = analyzer.compute_all(empty)
        assert result.empty

    def test_sorts_by_date(self, analyzer):
        import random
        dates = [date.today() - timedelta(days=i) for i in range(100)]
        shuffled = list(dates)
        random.shuffle(shuffled)
        df = pd.DataFrame([{"date": d, "close": 100.0, "open": 99.0, "high": 101.0, "low": 98.0, "volume": 1000} for d in shuffled])
        result = analyzer.compute_all(df)
        assert result["date"].is_monotonic_increasing


class TestGenerateSignal:
    def test_buy_signal_on_oversold(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        df.iloc[-1, df.columns.get_loc("rsi")] = 25.0
        signal = analyzer.generate_signal(df)
        assert signal["action"] in ("BUY", "HOLD")

    def test_sell_signal_on_overbought(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        df.iloc[-1, df.columns.get_loc("rsi")] = 75.0
        signal = analyzer.generate_signal(df)
        assert signal["action"] in ("SELL", "HOLD")

    def test_neutral_on_insufficient_data(self, analyzer):
        small = pd.DataFrame([{"date": date.today(), "close": 100.0, "open": 99.0, "high": 101.0, "low": 98.0, "volume": 1000} for _ in range(10)])
        signal = analyzer.generate_signal(small)
        assert signal["action"] == "NEUTRAL"
        assert signal["confidence"] == 0.0

    def test_confidence_between_0_and_1(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        signal = analyzer.generate_signal(df)
        assert 0 <= signal["confidence"] <= 1

    def test_reasons_is_list(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        signal = analyzer.generate_signal(df)
        assert isinstance(signal["reasons"], list)

    def test_score_is_float(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        signal = analyzer.generate_signal(df)
        assert isinstance(signal["score"], float)

    def test_price_above_sma_adds_reason(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        df.iloc[-1, df.columns.get_loc("close")] = df.iloc[-1]["sma_20"] * 1.1
        signal = analyzer.generate_signal(df)
        reasons_text = " ".join(signal["reasons"])
        assert "выше" in reasons_text or "BUY" in signal["action"]

    def test_price_below_bb_lower_adds_reason(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        df.iloc[-1, df.columns.get_loc("close")] = df.iloc[-1]["bb_lower"] * 0.99
        signal = analyzer.generate_signal(df)
        reasons_text = " ".join(signal["reasons"])
        assert "Bollinger" in reasons_text or "отскок" in reasons_text


class TestIndividualIndicators:
    def test_rsi_values_in_range(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        rsi_values = df["rsi"].dropna()
        assert rsi_values.between(0, 100).all()

    def test_sma_values(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        assert df["sma_20"].iloc[-1] > 0
        assert df["sma_50"].iloc[-1] > 0

    def test_bb_upper_greater_than_lower(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        valid = df.dropna(subset=["bb_upper", "bb_lower"])
        assert (valid["bb_upper"] >= valid["bb_lower"]).all()

    def test_atr_positive(self, analyzer, sample_df):
        df = analyzer.compute_all(sample_df)
        assert (df["atr"].dropna() >= 0).all()
