from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.analysis.correlation import CorrelationAnalyzer


class TestDiversificationPenalty:
    def setup_method(self):
        self.analyzer = CorrelationAnalyzer()

    def test_no_existing_tickers(self):
        assert self.analyzer.diversification_penalty("SBER", [], MagicMock()) == 0.0

    def test_returns_zero_when_no_matrix(self):
        with patch.object(self.analyzer, "_load_correlation_matrix", return_value=None):
            result = self.analyzer.diversification_penalty("SBER", ["GAZP"], MagicMock())
            assert result == 0.0

    def test_high_correlation_penalty(self):
        matrix = pd.DataFrame(
            {"SBER": [1.0, 0.95], "GAZP": [0.95, 1.0]},
            index=["SBER", "GAZP"],
        )
        with patch.object(self.analyzer, "_load_correlation_matrix", return_value=matrix):
            result = self.analyzer.diversification_penalty("SBER", ["GAZP"], MagicMock())
            assert result > 0.0

    def test_low_correlation_no_penalty(self):
        matrix = pd.DataFrame(
            {"SBER": [1.0, 0.3], "GAZP": [0.3, 1.0]},
            index=["SBER", "GAZP"],
        )
        with patch.object(self.analyzer, "_load_correlation_matrix", return_value=matrix):
            result = self.analyzer.diversification_penalty("SBER", ["GAZP"], MagicMock())
            assert result == 0.0

    def test_async_no_existing(self):
        import asyncio

        result = asyncio.run(self.analyzer.diversification_penalty_async("SBER", [], MagicMock()))
        assert result == 0.0

    def test_async_no_matrix(self):
        import asyncio

        async def run():
            with patch.object(self.analyzer, "_load_correlation_matrix_async", return_value=None):
                return await self.analyzer.diversification_penalty_async("SBER", ["GAZP"], MagicMock())

        result = asyncio.run(run())
        assert result == 0.0


class TestLoadCorrelationMatrix:
    def setup_method(self):
        self.analyzer = CorrelationAnalyzer()

    def test_less_than_two_instruments(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [MagicMock()]
        result = self.analyzer._load_correlation_matrix(["SBER"], db)
        assert result is None

    def test_fewer_than_20_prices(self):
        db = MagicMock()
        inst1, inst2 = MagicMock(), MagicMock()
        inst1.id, inst2.id = 1, 2
        inst1.ticker, inst2.ticker = "SBER", "GAZP"
        db.query.return_value.filter.return_value.all.return_value = [inst1, inst2]
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [MagicMock() for _ in range(10)]

        result = self.analyzer._load_correlation_matrix(["SBER", "GAZP"], db)
        assert result is None
