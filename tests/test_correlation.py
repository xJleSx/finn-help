from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from src.analysis.correlation import CorrelationAnalyzer


@pytest.fixture
def analyzer():
    return CorrelationAnalyzer()


@pytest.fixture
def high_corr_matrix() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    base = np.cumsum(rng.normal(0, 1, 100))
    return pd.DataFrame(
        {
            "SBER": base + rng.normal(0, 0.5, 100),
            "GAZP": base + rng.normal(0, 0.5, 100),
        },
        index=pd.date_range("2024-01-01", periods=100, freq="D"),
    )


@pytest.fixture
def low_corr_matrix() -> pd.DataFrame:
    rng = np.random.default_rng(43)
    return pd.DataFrame(
        {
            "SBER": np.cumsum(rng.normal(0, 1, 100)),
            "GAZP": np.cumsum(rng.normal(0, 1, 100)),
        },
        index=pd.date_range("2024-01-01", periods=100, freq="D"),
    )


class TestDiversificationPenalty:
    def test_no_existing_tickers(self, analyzer):
        assert analyzer.diversification_penalty("SBER", [], None) == 0.0

    def test_returns_zero_when_ticker_not_in_matrix(self, analyzer):
        analyzer._load_correlation_matrix = lambda *a: pd.DataFrame(
            {"GAZP": [1.0]}, index=["GAZP"]
        )
        result = analyzer.diversification_penalty("SBER", ["GAZP"], None)
        assert result == 0.0

    def test_high_absolute_correlation_penalty(self, analyzer):
        corr_matrix = pd.DataFrame(
            {"SBER": [1.0, 0.95], "GAZP": [0.95, 1.0]},
            index=["SBER", "GAZP"],
        )
        analyzer._load_correlation_matrix = lambda *a: corr_matrix
        result = analyzer.diversification_penalty("SBER", ["GAZP"], None)
        assert result > 0.0

    def test_low_correlation_no_penalty(self, analyzer, low_corr_matrix):
        returns = low_corr_matrix.pct_change().dropna()
        corr_matrix = returns.corr(method="pearson")

        original_load = analyzer._load_correlation_matrix
        analyzer._load_correlation_matrix = lambda *a: corr_matrix
        try:
            result = analyzer.diversification_penalty("SBER", ["GAZP"], None)
            assert result == 0.0
        finally:
            analyzer._load_correlation_matrix = original_load

    def test_absolute_correlation_used(self, analyzer):
        matrix = pd.DataFrame(
            {"SBER": [1.0, -0.95], "GAZP": [-0.95, 1.0]},
            index=["SBER", "GAZP"],
        )
        analyzer._load_correlation_matrix = lambda *a: matrix
        result = analyzer.diversification_penalty("SBER", ["GAZP"], None)
        assert result > 0.0

    def test_penalty_capped_at_reasonable(self, analyzer):
        matrix = pd.DataFrame(
            {"SBER": [1.0, 0.999], "GAZP": [0.999, 1.0]},
            index=["SBER", "GAZP"],
        )
        analyzer._load_correlation_matrix = lambda *a: matrix
        result = analyzer.diversification_penalty("SBER", ["GAZP"], None)
        assert result <= 1.0

    def test_multiple_existing_tickers(self, analyzer):
        matrix = pd.DataFrame(
            {"SBER": [1.0, 0.8, 0.3], "GAZP": [0.8, 1.0, 0.2], "LKOH": [0.3, 0.2, 1.0]},
            index=["SBER", "GAZP", "LKOH"],
        )
        analyzer._load_correlation_matrix = lambda *a: matrix
        result = analyzer.diversification_penalty("SBER", ["GAZP", "LKOH"], None)
        assert result > 0.0


class TestDiversificationPenaltyAsync:
    @pytest.mark.asyncio
    async def test_no_existing_tickers(self, analyzer):
        result = await analyzer.diversification_penalty_async("SBER", [], None)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_high_correlation_async(self, analyzer):
        matrix = pd.DataFrame(
            {"SBER": [1.0, 0.95], "GAZP": [0.95, 1.0]},
            index=["SBER", "GAZP"],
        )
        analyzer._load_correlation_matrix_async = AsyncMock(return_value=matrix)
        result = await analyzer.diversification_penalty_async("SBER", ["GAZP"], None)
        assert result > 0.0


class TestThreshold:
    def test_default_threshold(self):
        assert CorrelationAnalyzer.THRESHOLD == 0.7

    def test_penalty_at_threshold(self, analyzer):
        matrix = pd.DataFrame(
            {"SBER": [1.0, 0.7], "GAZP": [0.7, 1.0]},
            index=["SBER", "GAZP"],
        )
        analyzer._load_correlation_matrix = lambda *a: matrix
        result = analyzer.diversification_penalty("SBER", ["GAZP"], None)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_penalty_just_above_threshold(self, analyzer):
        matrix = pd.DataFrame(
            {"SBER": [1.0, 0.71], "GAZP": [0.71, 1.0]},
            index=["SBER", "GAZP"],
        )
        analyzer._load_correlation_matrix = lambda *a: matrix
        result = analyzer.diversification_penalty("SBER", ["GAZP"], None)
        assert result == pytest.approx(0.02, abs=1e-6)
