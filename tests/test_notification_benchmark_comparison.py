from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.notifications.benchmark_comparison import BenchmarkComparison, compare_benchmarks, format_benchmark_comparison


class TestCompareBenchmarks:
    @patch("src.notifications.benchmark_comparison.get_session")
    def test_no_data_returns_none(self, mock_get_session):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_get_session.return_value.__enter__.return_value = mock_db
        result = compare_benchmarks(7)
        assert result is None


class TestFormatBenchmarkComparison:
    def test_with_data(self):
        cmp = BenchmarkComparison(portfolio_return_pct=2.5, bond_index_return_pct=1.8, rgbir_return_pct=1.2, deposit_return_pct=0.5, alpha_pct=0.7, reason="good", period_label="7 дней")
        text = format_benchmark_comparison(cmp)
        assert "+250" in text
