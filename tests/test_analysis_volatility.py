from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.volatility import (
    VolatilityForecaster,
    VolatilityRegimeDetector,
    ewma_volatility,
    garch_volatility,
    garman_klass_volatility,
    parkinson_volatility,
    volatility_cones,
    yang_zhang_volatility,
)


class TestParkinsonVolatility:
    def test_basic(self):
        highs = np.array([110.0, 112.0, 111.0, 115.0] * 10)
        lows = np.array([90.0, 92.0, 89.0, 95.0] * 10)
        result = parkinson_volatility(highs, lows, period=5)
        assert len(result) == len(highs)
        assert not np.isnan(result).all()

    def test_insufficient_data(self):
        result = parkinson_volatility(np.array([100.0, 101.0]), np.array([99.0, 100.0]), period=20)
        assert np.all(np.isnan(result))


class TestGarmanKlassVolatility:
    def test_basic(self):
        o = np.array([100.0] * 40)
        h = np.array([110.0] * 40)
        l = np.array([90.0] * 40)
        c = np.array([105.0] * 40)
        result = garman_klass_volatility(o, h, l, c, period=5)
        assert len(result) == 40

    def test_insufficient_data(self):
        result = garman_klass_volatility(
            np.array([100.0, 101.0]), np.array([102.0, 103.0]), np.array([99.0, 100.0]), np.array([101.0, 102.0]), period=20
        )
        assert np.all(np.isnan(result))


class TestYangZhangVolatility:
    def test_basic(self):
        o = np.array([100.0] * 40)
        h = np.array([110.0] * 40)
        l = np.array([90.0] * 40)
        c = np.array([105.0] * 40)
        result = yang_zhang_volatility(o, h, l, c, period=5)
        assert len(result) == 40

    def test_insufficient_data(self):
        result = yang_zhang_volatility(
            np.array([100.0, 101.0]), np.array([102.0, 103.0]), np.array([99.0, 100.0]), np.array([101.0, 102.0]), period=20
        )
        assert np.all(np.isnan(result))


class TestEwmaVolatility:
    def test_basic(self):
        returns = np.array([0.01, -0.02, 0.015, -0.01] * 10)
        result = ewma_volatility(returns)
        assert len(result) == len(returns)
        assert np.all(result >= 0)

    def test_flat_returns(self):
        returns = np.zeros(10)
        result = ewma_volatility(returns)
        assert np.allclose(result, 0.0)


class TestGarchVolatility:
    def test_basic(self):
        returns = np.array([0.01, -0.02, 0.015, -0.01] * 10)
        result = garch_volatility(returns)
        assert isinstance(result, tuple)
        assert len(result) == 5

    def test_short_returns(self):
        result = garch_volatility(np.array([0.01, 0.02]))
        omega, alpha, beta, long_run_var, forecast_vol = result
        assert isinstance(forecast_vol, float)


class TestVolatilityCones:
    def test_basic(self):
        df = pd.DataFrame({"close": [100.0 + i for i in range(50)]})
        result = volatility_cones(df)
        assert isinstance(result, dict)
        assert "5" in result or "10" in result

    def test_short_df(self):
        df = pd.DataFrame({"close": [100.0, 101.0]})
        result = volatility_cones(df)
        assert isinstance(result, dict)

    def test_all_keys_present(self):
        df = pd.DataFrame({"close": [100.0 + i for i in range(100)]})
        result = volatility_cones(df)
        assert "5" in result
        assert "50%" in result["5"]


class TestVolatilityRegimeDetector:
    def test_init(self):
        detector = VolatilityRegimeDetector()
        assert detector is not None

    def test_detect_with_data(self):
        detector = VolatilityRegimeDetector()
        df = pd.DataFrame({"close": [100 + i for i in range(100)]})
        result = detector.detect(df, df)
        assert isinstance(result, dict)


class TestVolatilityForecaster:
    def test_ewma_forecast(self):
        returns = np.array([0.01, -0.02, 0.015, -0.01] * 10)
        result = VolatilityForecaster.ewma_forecast(returns, steps=5)
        assert len(result) == 5
        assert np.all(result >= 0)

    def test_garch_forecast(self):
        returns = np.array([0.01, -0.02, 0.015, -0.01] * 10)
        result = VolatilityForecaster.garch_forecast(returns, steps=3)
        assert len(result) == 3
        assert np.all(result >= 0)

    def test_forecast_term_structure(self):
        returns = np.array([0.01, -0.02, 0.015, -0.01] * 10)
        result = VolatilityForecaster.forecast_term_structure(returns, method="ewma", steps=4)
        assert len(result) == 4
