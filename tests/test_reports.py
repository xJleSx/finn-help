from __future__ import annotations

from src.reports import (
    generate_analysis_csv,
    generate_backtest_csv,
    generate_portfolio_csv,
    generate_sector_report_csv,
    generate_signals_csv,
)


class TestPortfolioCSV:
    def test_generate_empty(self):
        result = generate_portfolio_csv([])
        assert "Тикер" in result
        assert "Название" in result

    def test_generate_with_positions(self):
        positions = [
            {
                "ticker": "SBER",
                "name": "Сбер",
                "quantity": 100,
                "avg_price": 250,
                "current_price": 280,
                "value": 28000,
                "allocation_pct": 50.0,
                "profit_pct": 12.0,
            },
            {
                "ticker": "GAZP",
                "name": "Газпром",
                "quantity": 50,
                "avg_price": 150,
                "current_price": 170,
                "value": 8500,
                "allocation_pct": 30.0,
                "profit_pct": 13.3,
            },
        ]
        result = generate_portfolio_csv(positions)
        assert "SBER" in result
        assert "GAZP" in result
        assert "12.0%" in result
        assert "50.0%" in result


class TestSignalsCSV:
    def test_generate_empty(self):
        result = generate_signals_csv([])
        assert "Тикер" in result

    def test_generate_with_signals(self):
        signals = [
            {
                "ticker": "SBER",
                "action": "BUY",
                "confidence": 0.85,
                "weighted_score": 0.7,
                "reasons": ["RSI oversold", "MACD crossover"],
            },
        ]
        result = generate_signals_csv(signals)
        assert "SBER" in result
        assert "BUY" in result
        assert "RSI oversold" in result


class TestAnalysisCSV:
    def test_generate(self):
        signal = {
            "action": "BUY",
            "confidence": 0.9,
            "weighted_score": 0.75,
            "max_portfolio_pct": 15,
            "reasons": ["Strong trend", "Volume spike"],
        }
        prices = [{"date": "2024-01-01", "close": 250.0}, {"date": "2024-01-02", "close": 255.0}]
        result = generate_analysis_csv("SBER", signal, prices)
        assert "SBER" in result
        assert "BUY" in result
        assert "0.9" in result
        assert "2024-01-01" in result


class FakeBacktestResult:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestBacktestCSV:
    def test_generate(self):
        result = FakeBacktestResult(
            portfolio_return=0.15,
            benchmark_return=0.10,
            alpha=0.05,
            portfolio_sharpe=1.2,
            portfolio_sortino=1.5,
            portfolio_max_dd=0.12,
            win_rate=0.65,
            profit_factor=2.1,
            trades=50,
            total_commission=1000,
            total_slippage=500,
            monte_carlo=None,
            regime=None,
            dates=["2024-01-01", "2024-01-02"],
            portfolio_returns=[0.01, 0.02],
            benchmark_returns=[0.005, 0.01],
        )
        result = generate_backtest_csv(result)
        assert "15.00%" in result
        assert "1.20" in result
        assert "50" in result


class TestSectorReportCSV:
    def test_generate(self):
        sector_perf = {"Нефть и газ": 0.05, "Банки": 0.03}
        sector_vol = {"Нефть и газ": 0.25, "IT": 0.35}
        result = generate_sector_report_csv(sector_perf, sector_vol)
        assert "Нефть и газ" in result
        assert "5.0%" in result or "5.00%" in result
        assert "IT" in result
