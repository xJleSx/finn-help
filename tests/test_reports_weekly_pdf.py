from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestPortfolioTickers:
    @patch("src.reports.weekly_pdf.get_session")
    def test_empty_portfolio_returns_empty_list(self, mock_get_session):
        mock_db = MagicMock()
        mock_db.query.return_value.options.return_value.all.return_value = []
        mock_get_session.return_value = mock_db

        from src.reports.weekly_pdf import _portfolio_tickers

        result = _portfolio_tickers()
        assert result == []

    @patch("src.reports.weekly_pdf.get_session")
    def test_returns_tickers_from_portfolio_with_instrument(self, mock_get_session):
        mock_db = MagicMock()
        mock_instrument = MagicMock()
        mock_instrument.ticker = "SBER"
        mock_row = MagicMock()
        mock_row.instrument = mock_instrument
        mock_db.query.return_value.options.return_value.all.return_value = [mock_row]
        mock_get_session.return_value = mock_db

        from src.reports.weekly_pdf import _portfolio_tickers

        result = _portfolio_tickers()
        assert result == ["SBER"]

    @patch("src.reports.weekly_pdf.get_session")
    def test_falls_back_to_instrument_query_when_relation_none(self, mock_get_session):
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.instrument = None
        mock_row.instrument_id = 1
        mock_db.query.return_value.options.return_value.all.return_value = [mock_row]
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(ticker="GAZP")
        mock_get_session.return_value = mock_db

        from src.reports.weekly_pdf import _portfolio_tickers

        result = _portfolio_tickers()
        assert result == ["GAZP"]

    @patch("src.reports.weekly_pdf.get_session")
    def test_skips_instruments_without_ticker(self, mock_get_session):
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.instrument = None
        mock_row.instrument_id = 1
        mock_db.query.return_value.options.return_value.all.return_value = [mock_row]
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(ticker=None)
        mock_get_session.return_value = mock_db

        from src.reports.weekly_pdf import _portfolio_tickers

        result = _portfolio_tickers()
        assert result == []

    @patch("src.reports.weekly_pdf.get_session")
    def test_closes_db_session(self, mock_get_session):
        mock_db = MagicMock()
        mock_db.query.return_value.options.return_value.all.return_value = []
        mock_get_session.return_value = mock_db

        from src.reports.weekly_pdf import _portfolio_tickers

        _portfolio_tickers()
        mock_db.close.assert_called_once()

    @patch("src.reports.weekly_pdf.get_session")
    def test_three_instruments(self, mock_get_session):
        mock_db = MagicMock()
        rows = []
        for ticker in ["SBER", "LKOH", "GAZP"]:
            mock_instrument = MagicMock()
            mock_instrument.ticker = ticker
            row = MagicMock()
            row.instrument = mock_instrument
            rows.append(row)
        mock_db.query.return_value.options.return_value.all.return_value = rows
        mock_get_session.return_value = mock_db

        from src.reports.weekly_pdf import _portfolio_tickers

        result = _portfolio_tickers()
        assert result == ["SBER", "LKOH", "GAZP"]


class TestGenerateWeeklyChart:
    @patch("matplotlib.pyplot", create=True)
    @patch("src.reports.weekly_pdf._portfolio_tickers")
    @patch("src.reports.weekly_pdf.run_personal_backtest")
    def test_returns_bytes_when_successful(
        self, mock_backtest, mock_tickers, mock_plt
    ):
        mock_tickers.return_value = ["SBER"]
        mock_result = MagicMock()
        mock_result.equity_curve = [
            {"date": "2024-01-01", "portfolio": 100000.0, "benchmark": 100000.0},
            {"date": "2024-01-02", "portfolio": 101000.0, "benchmark": 100500.0},
        ]
        mock_result.monthly_returns = [
            {"month": "2024-01", "return": 0.05},
        ]
        mock_result.total_return = 0.05
        mock_result.benchmark_return = 0.03
        mock_result.max_drawdown = -0.02
        mock_result.alpha = 0.02
        mock_result.sharpe = 1.5
        mock_result.sortino = 2.0
        mock_result.win_rate = 0.6
        mock_backtest.return_value = mock_result

        mock_fig = MagicMock()
        mock_axes = [MagicMock(), MagicMock(), MagicMock()]
        mock_plt.subplots.return_value = (mock_fig, mock_axes)

        from src.reports.weekly_pdf import generate_weekly_chart

        result = generate_weekly_chart()
        assert isinstance(result, bytes)
        assert len(result) > 0

    @patch("matplotlib.pyplot", create=True)
    @patch("src.reports.weekly_pdf._portfolio_tickers")
    @patch("src.reports.weekly_pdf.run_personal_backtest")
    def test_returns_none_when_no_equity_curve(
        self, mock_backtest, mock_tickers, mock_plt
    ):
        mock_tickers.return_value = ["SBER"]
        mock_result = MagicMock()
        mock_result.equity_curve = []
        mock_backtest.return_value = mock_result

        from src.reports.weekly_pdf import generate_weekly_chart

        result = generate_weekly_chart()
        assert result is None

    @patch("src.reports.weekly_pdf.personal")
    @patch("matplotlib.pyplot", create=True)
    @patch("src.reports.weekly_pdf._portfolio_tickers")
    @patch("src.reports.weekly_pdf.run_personal_backtest")
    def test_uses_fallback_tickers_when_portfolio_empty(
        self, mock_backtest, mock_tickers, mock_plt, mock_personal
    ):
        mock_personal.get.return_value = ["SBER", "LKOH", "GAZP"]
        mock_tickers.return_value = []
        mock_result = MagicMock()
        mock_result.equity_curve = [
            {"date": "2024-01-01", "portfolio": 100000.0, "benchmark": 100000.0},
        ]
        mock_result.monthly_returns = []
        mock_result.total_return = 0.0
        mock_result.benchmark_return = 0.0
        mock_result.max_drawdown = 0.0
        mock_result.alpha = 0.0
        mock_result.sharpe = 0.0
        mock_result.sortino = 0.0
        mock_result.win_rate = 0.0
        mock_backtest.return_value = mock_result

        mock_fig = MagicMock()
        mock_axes = [MagicMock(), MagicMock(), MagicMock()]
        mock_plt.subplots.return_value = (mock_fig, mock_axes)

        from src.reports.weekly_pdf import generate_weekly_chart

        generate_weekly_chart()
        mock_backtest.assert_called_once()
        tickers_arg = mock_backtest.call_args[1]["tickers"]
        assert tickers_arg == ["SBER", "LKOH", "GAZP"]

    @patch("matplotlib.pyplot", create=True)
    @patch("src.reports.weekly_pdf._portfolio_tickers")
    @patch("src.reports.weekly_pdf.run_personal_backtest")
    def test_handles_single_position(
        self, mock_backtest, mock_tickers, mock_plt
    ):
        mock_tickers.return_value = ["SBER"]
        mock_result = MagicMock()
        mock_result.equity_curve = [
            {"date": "2024-01-01", "portfolio": 100000.0, "benchmark": 100000.0},
        ]
        mock_result.monthly_returns = []
        mock_result.total_return = 0.01
        mock_result.benchmark_return = 0.0
        mock_result.max_drawdown = 0.0
        mock_result.alpha = 0.01
        mock_result.sharpe = 0.5
        mock_result.sortino = 0.8
        mock_result.win_rate = 0.55
        mock_backtest.return_value = mock_result

        mock_fig = MagicMock()
        mock_axes = [MagicMock(), MagicMock(), MagicMock()]
        mock_plt.subplots.return_value = (mock_fig, mock_axes)

        from src.reports.weekly_pdf import generate_weekly_chart

        result = generate_weekly_chart()
        assert isinstance(result, bytes)

    @patch("matplotlib.pyplot", create=True)
    @patch("src.reports.weekly_pdf._portfolio_tickers")
    @patch("src.reports.weekly_pdf.run_personal_backtest")
    def test_handles_negative_returns(
        self, mock_backtest, mock_tickers, mock_plt
    ):
        mock_tickers.return_value = ["SBER"]
        mock_result = MagicMock()
        mock_result.equity_curve = [
            {"date": "2024-01-01", "portfolio": 100000.0, "benchmark": 100000.0},
            {"date": "2024-01-02", "portfolio": 95000.0, "benchmark": 99000.0},
        ]
        mock_result.monthly_returns = [
            {"month": "2024-01", "return": -0.05},
        ]
        mock_result.total_return = -0.05
        mock_result.benchmark_return = -0.01
        mock_result.max_drawdown = -0.05
        mock_result.alpha = -0.04
        mock_result.sharpe = -0.5
        mock_result.sortino = -0.8
        mock_result.win_rate = 0.3
        mock_backtest.return_value = mock_result

        mock_fig = MagicMock()
        mock_axes = [MagicMock(), MagicMock(), MagicMock()]
        mock_plt.subplots.return_value = (mock_fig, mock_axes)

        from src.reports.weekly_pdf import generate_weekly_chart

        result = generate_weekly_chart()
        assert isinstance(result, bytes)

    @patch("matplotlib.pyplot", create=True)
    @patch("src.reports.weekly_pdf._portfolio_tickers")
    @patch("src.reports.weekly_pdf.run_personal_backtest")
    def test_does_not_close_figure_when_none(
        self, mock_backtest, mock_tickers, mock_plt
    ):
        mock_tickers.return_value = ["SBER"]
        mock_result = MagicMock()
        mock_result.equity_curve = []
        mock_backtest.return_value = mock_result

        from src.reports.weekly_pdf import generate_weekly_chart

        generate_weekly_chart()
        mock_plt.close.assert_not_called()

    @patch("matplotlib.pyplot", create=True)
    @patch("src.reports.weekly_pdf._portfolio_tickers")
    @patch("src.reports.weekly_pdf.run_personal_backtest")
    def test_closes_figure_when_chart_generated(
        self, mock_backtest, mock_tickers, mock_plt
    ):
        mock_tickers.return_value = ["SBER"]
        mock_result = MagicMock()
        mock_result.equity_curve = [
            {"date": "2024-01-01", "portfolio": 100000.0, "benchmark": 100000.0},
        ]
        mock_result.monthly_returns = []
        mock_result.total_return = 0.0
        mock_result.benchmark_return = 0.0
        mock_result.max_drawdown = 0.0
        mock_result.alpha = 0.0
        mock_result.sharpe = 0.0
        mock_result.sortino = 0.0
        mock_result.win_rate = 0.0
        mock_backtest.return_value = mock_result

        mock_fig = MagicMock()
        mock_axes = [MagicMock(), MagicMock(), MagicMock()]
        mock_plt.subplots.return_value = (mock_fig, mock_axes)

        from src.reports.weekly_pdf import generate_weekly_chart

        generate_weekly_chart()
        mock_plt.close.assert_called_once_with(mock_fig)

    @patch("matplotlib.pyplot", create=True)
    @patch("src.reports.weekly_pdf._portfolio_tickers")
    @patch("src.reports.weekly_pdf.run_personal_backtest")
    def test_exception_returns_none(
        self, mock_backtest, mock_tickers, mock_plt
    ):
        mock_tickers.side_effect = RuntimeError("unexpected error")

        from src.reports.weekly_pdf import generate_weekly_chart

        result = generate_weekly_chart()
        assert result is None
