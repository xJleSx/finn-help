"""Tests for FundamentalAnalyzer"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest


@pytest.fixture
def analyzer():
    from src.analysis.fundamental import FundamentalAnalyzer
    return FundamentalAnalyzer()


@pytest.fixture
def three_year_prices():
    dates = [date.today() - timedelta(days=i) for i in range(365 * 3, 0, -1)]
    close = 100.0
    rows = []
    for d in dates:
        rows.append({"date": d, "open": close, "high": close * 1.02, "low": close * 0.98, "close": close, "volume": 1_000_000})
        close *= 1.001
    return pd.DataFrame(rows)


class TestAnalyze:
    def test_returns_dict(self, analyzer, three_year_prices):
        divs = pd.DataFrame()
        result = analyzer.analyze(three_year_prices, divs)
        assert isinstance(result, dict)

    def test_has_risk_key(self, analyzer, three_year_prices):
        result = analyzer.analyze(three_year_prices, pd.DataFrame())
        assert "risk" in result

    def test_risk_between_0_and_1(self, analyzer, three_year_prices):
        result = analyzer.analyze(three_year_prices, pd.DataFrame())
        assert 0 <= result["risk"] <= 1

    def test_has_anomalies_key(self, analyzer, three_year_prices):
        result = analyzer.analyze(three_year_prices, pd.DataFrame())
        assert "anomalies" in result

    def test_has_signals_key(self, analyzer, three_year_prices):
        result = analyzer.analyze(three_year_prices, pd.DataFrame())
        assert "signals" in result

    def test_empty_prices_returns_default_risk(self, analyzer):
        result = analyzer.analyze(pd.DataFrame(), pd.DataFrame())
        assert result["risk"] == 0.5

    def test_insufficient_data_returns_default_risk(self, analyzer):
        small = pd.DataFrame([{"date": date.today(), "close": 100.0, "open": 99.0, "high": 101.0, "low": 98.0, "volume": 1000} for _ in range(5)])
        result = analyzer.analyze(small, pd.DataFrame())
        assert result["risk"] == 0.5

    def test_dividend_yield_adds_signal(self, analyzer, three_year_prices):
        divs = pd.DataFrame([
            {"date": date.today() - timedelta(days=30), "amount": 5.0},
            {"date": date.today() - timedelta(days=400), "amount": 4.5},
        ])
        result = analyzer.analyze(three_year_prices, divs)
        signals_text = " ".join(result["signals"])
        assert "дивидендн" in signals_text

    def test_no_recent_dividends_adds_anomaly(self, analyzer, three_year_prices):
        divs = pd.DataFrame([
            {"date": date.today() - timedelta(days=800), "amount": 5.0},
        ])
        result = analyzer.analyze(three_year_prices, divs)
        anomalies_text = " ".join(result["anomalies"])
        assert "нет дивидендных" in anomalies_text

    def test_high_volatility_adds_anomaly(self, analyzer):
        dates = [date.today() - timedelta(days=i) for i in range(365 * 3, 0, -1)]
        rows = []
        for d in dates:
            rows.append({"date": d, "open": 100.0, "high": 110.0, "low": 90.0, "close": 100.0 * (1 + (d.day % 2) * 0.05 - 0.025), "volume": 1_000_000})
        df = pd.DataFrame(rows)
        result = analyzer.analyze(df, pd.DataFrame())
        assert result["risk"] >= 0.15

    def test_anomalies_is_list(self, analyzer, three_year_prices):
        result = analyzer.analyze(three_year_prices, pd.DataFrame())
        assert isinstance(result["anomalies"], list)

    def test_signals_is_list(self, analyzer, three_year_prices):
        result = analyzer.analyze(three_year_prices, pd.DataFrame())
        assert isinstance(result["signals"], list)
