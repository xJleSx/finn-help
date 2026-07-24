from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.correlation import (
    CorrelationAnalyzer,
    ewma_correlation,
    hierarchical_clustering,
    kendall_correlation,
    rolling_correlation,
    spearman_correlation,
    tail_dependence,
)


class TestCorrelationAnalyzer:
    def test_init_defaults(self):
        analyzer = CorrelationAnalyzer()
        assert analyzer.THRESHOLD == 0.7


class TestRollingCorrelation:
    def test_basic(self):
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0], "b": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]})
        result = rolling_correlation(df, window=5)
        assert isinstance(result, dict)

    def test_pair_names(self):
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [2.0, 4.0, 6.0, 8.0, 10.0], "c": [3.0, 6.0, 9.0, 12.0, 15.0]})
        result = rolling_correlation(df, window=3)
        assert "a_b" in result
        assert "a_c" in result
        assert "b_c" in result


class TestSpearmanCorrelation:
    def test_perfect_positive(self):
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [2.0, 4.0, 6.0, 8.0, 10.0]})
        result = spearman_correlation(df)
        assert abs(result.loc["a", "b"] - 1.0) < 0.001

    def test_short_series(self):
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [2.0, 3.0]})
        result = spearman_correlation(df)
        assert abs(result.loc["a", "b"] - 1.0) < 0.001


class TestKendallCorrelation:
    def test_basic(self):
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [2.0, 4.0, 6.0, 8.0, 10.0]})
        result = kendall_correlation(df)
        assert abs(result.loc["a", "b"] - 1.0) < 0.001


class TestTailDependence:
    def test_short_series(self):
        a = pd.Series([1.0, 2.0, 3.0])
        b = pd.Series([2.0, 3.0, 4.0])
        assert tail_dependence(a, b, upper_tail=True) == 0.0

    def test_long_enough(self):
        n = 50
        a = pd.Series(np.random.default_rng(42).uniform(size=n))
        b = pd.Series(np.random.default_rng(42).uniform(size=n))
        result = tail_dependence(a, b, upper_tail=True)
        assert 0 <= result <= 1


class TestEwmaCorrelation:
    def test_basic(self):
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0] * 3, "b": [2.0, 4.0, 6.0, 8.0, 10.0] * 3})
        result = ewma_correlation(df)
        assert isinstance(result, pd.DataFrame)


class TestHierarchicalClustering:
    def test_basic(self):
        data = pd.DataFrame({"a": [1.0, 2.0, 5.0], "b": [2.0, 1.0, 5.0], "c": [5.0, 5.0, 1.0]})
        result = hierarchical_clustering(data.corr())
        assert "linkage_matrix" in result
        assert "labels" in result
