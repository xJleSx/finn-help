from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.volatility import VOLATILITY_REGIMES, VolatilityRegimeDetector


class TestClassify:
    def setup_method(self):
        self.detector = VolatilityRegimeDetector()

    def test_low_regime(self):
        r = self.detector._classify(0.005, 0.1)
        assert r == "LOW"

    def test_normal_regime(self):
        r = self.detector._classify(0.015, 0.2)
        assert r == "NORMAL"

    def test_high_regime(self):
        r = self.detector._classify(0.03, 0.4)
        assert r == "HIGH"

    def test_boundary_low_normal(self):
        r = self.detector._classify(
            VOLATILITY_REGIMES["LOW"]["threshold_atr"] - 0.001,
            VOLATILITY_REGIMES["LOW"]["threshold_hv"] - 0.01,
        )
        assert r == "LOW"

    def test_boundary_normal_high(self):
        r = self.detector._classify(
            VOLATILITY_REGIMES["NORMAL"]["threshold_atr"] - 0.001,
            VOLATILITY_REGIMES["NORMAL"]["threshold_hv"] - 0.01,
        )
        assert r == "NORMAL"


class TestWeightAdjustment:
    def setup_method(self):
        self.detector = VolatilityRegimeDetector()

    def test_high_adjustment(self):
        adj = self.detector._weight_adjustment("HIGH")
        assert adj["technical_mult"] == 0.7
        assert adj["ml_mult"] == 0.6
        assert adj["fundamental_mult"] == 1.3

    def test_low_adjustment(self):
        adj = self.detector._weight_adjustment("LOW")
        assert adj["technical_mult"] == 1.2
        assert adj["ml_mult"] == 1.2

    def test_normal_adjustment(self):
        adj = self.detector._weight_adjustment("NORMAL")
        assert all(v == 1.0 for v in adj.values())


class TestDetect:
    def setup_method(self):
        self.detector = VolatilityRegimeDetector()

    def test_empty_df(self):
        df = pd.DataFrame()
        result = self.detector.detect(df, pd.DataFrame())
        assert result["regime"] == "NORMAL"
        assert result["adjustment"] == 1.0

    def test_with_data(self):
        closes = [100.0 + i * 0.5 for i in range(30)]
        df = pd.DataFrame({"close": closes})
        ind_df = pd.DataFrame({"atr": [2.0] * 30})
        result = self.detector.detect(df, ind_df)
        assert "regime" in result
        assert "atr_ratio" in result
        assert "hv" in result
        assert isinstance(result["adjustment"], dict)

    def test_without_atr(self):
        closes = [100.0] * 30
        df = pd.DataFrame({"close": closes})
        ind_df = pd.DataFrame({"other": [1.0] * 30})
        result = self.detector.detect(df, ind_df)
        assert result["atr_ratio"] == 0.0

    def test_returns_expected_keys(self):
        closes = np.random.default_rng(42).normal(100, 2, 50)
        df = pd.DataFrame({"close": closes})
        result = self.detector.detect(df, pd.DataFrame({"atr": [1.5] * 50}))
        assert set(result.keys()) == {"regime", "atr_ratio", "hv", "adjustment"}
