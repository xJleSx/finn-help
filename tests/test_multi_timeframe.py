from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.multi_timeframe import MultiTimeframeAnalyzer


class TestResample:
    def setup_method(self):
        self.mtf = MultiTimeframeAnalyzer()

    def test_empty_df(self):
        df = pd.DataFrame()
        result = self.mtf._resample(df, 1)
        assert result is df  # returns same empty df

    def test_period_1_returns_sorted(self):
        df = pd.DataFrame({"date": [3, 1, 2], "close": [30, 10, 20]})
        result = self.mtf._resample(df, 1)
        assert result["close"].iloc[0] == 10

    def test_resample_weekly(self):
        dates = list(range(1, 31))
        df = pd.DataFrame(
            {
                "date": dates,
                "open": dates,
                "high": [d + 1 for d in dates],
                "low": [d - 1 for d in dates],
                "close": [d + 0.5 for d in dates],
                "volume": [100] * 30,
            }
        )
        result = self.mtf._resample(df, 5)
        assert len(result) <= 6
        assert "open" in result.columns
        assert "volume" in result.columns


class TestComputeIndicators:
    def setup_method(self):
        self.mtf = MultiTimeframeAnalyzer()

    def test_basic_indicators(self):
        df = pd.DataFrame({"close": [100 + i for i in range(100)]})
        result = self.mtf._compute_indicators(df)
        assert "sma_20" in result.columns
        assert "rsi" in result.columns
        assert "macd_line" in result.columns
        assert "macd_hist" in result.columns

    def test_rsi_values(self):
        rng = np.random.default_rng(42)
        close = 100.0 + np.cumsum(rng.normal(0, 2, 100))
        df = pd.DataFrame({"close": close})
        result = self.mtf._compute_indicators(df)
        assert not pd.isna(result["rsi"].iloc[-1])
        assert 0 <= result["rsi"].iloc[-1] <= 100


class TestTfSignal:
    def setup_method(self):
        self.mtf = MultiTimeframeAnalyzer()

    def test_empty_df(self):
        result = self.mtf._tf_signal(pd.DataFrame())
        assert result["direction"] == 0

    def test_single_row(self):
        df = pd.DataFrame({"close": [100]})
        result = self.mtf._tf_signal(df)
        assert result["direction"] == 0

    def test_overbought_rsi(self):
        df = pd.DataFrame(
            {"close": [100, 105], "rsi": [50, 75], "macd_hist": [0.0, 0.0], "sma_20": [120, 120], "sma_50": [120, 120]}
        )
        result = self.mtf._tf_signal(df)
        assert result["direction"] < 0

    def test_oversold_rsi(self):
        df = pd.DataFrame(
            {"close": [100, 95], "rsi": [50, 25], "macd_hist": [0.0, 0.0], "sma_20": [90, 90], "sma_50": [90, 90]}
        )
        result = self.mtf._tf_signal(df)
        assert result["direction"] > 0

    def test_macd_crossover_up(self):
        df = pd.DataFrame(
            {"close": [100, 102], "rsi": [50, 50], "macd_hist": [-0.5, 0.3], "sma_20": [90, 90], "sma_50": [90, 90]}
        )
        result = self.mtf._tf_signal(df)
        assert result["direction"] > 0


class TestConcordance:
    def setup_method(self):
        self.mtf = MultiTimeframeAnalyzer()

    def test_empty_dict(self):
        result = self.mtf.concordance({})
        assert result["agreement"] == 0.0

    def test_all_agree(self):
        row = {
            "close": [100, 102],
            "rsi": [50, 60],
            "macd_hist": [0.0, 0.0],
            "sma_20": [100, 101],
            "sma_50": [100, 100],
        }
        tf_data = {"daily": self.mtf._compute_indicators(pd.DataFrame(row))}
        result = self.mtf.concordance(tf_data)
        assert "agreement" in result
        assert "details" in result

    def test_compute_all(self):
        df = pd.DataFrame(
            {
                "date": list(range(100)),
                "open": [100] * 100,
                "high": [101] * 100,
                "low": [99] * 100,
                "close": [100 + i for i in range(100)],
                "volume": [1000] * 100,
            }
        )
        result = self.mtf.compute_all(df)
        assert "daily" in result
