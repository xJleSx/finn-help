from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.analysis.correlation_analysis import correlation_table


class TestCorrelationTable:
    def test_less_than_two_instruments(self):
        with patch("src.analysis.correlation_analysis.get_session") as mock_gs:
            db = MagicMock()
            mock_gs.return_value = db
            db.query.return_value.filter.return_value.all.return_value = [MagicMock()]

            result = correlation_table(["SBER"])
            assert "минимум 2" in result

    def test_not_enough_data(self):
        with patch("src.analysis.correlation_analysis.get_session") as mock_gs:
            db = MagicMock()
            inst1, inst2 = MagicMock(), MagicMock()
            inst1.id, inst2.id = 1, 2
            inst1.ticker, inst2.ticker = "SBER", "GAZP"
            db.query.return_value.filter.return_value.all.return_value = [inst1, inst2]
            db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [
                MagicMock() for _ in range(10)
            ]

            mock_gs.return_value = db
            result = correlation_table(["SBER", "GAZP"])
            assert "Недостаточно" in result or "минимум" in result

    def test_default_tickers_from_env(self, monkeypatch):
        monkeypatch.setenv("FAVORITE_TICKERS", "SBER,LKOH")
        with patch("src.analysis.correlation_analysis.get_session") as mock_gs:
            db = MagicMock()
            mock_gs.return_value = db
            inst1, inst2 = MagicMock(), MagicMock()
            inst1.id, inst2.id = 1, 2
            inst1.ticker, inst2.ticker = "SBER", "LKOH"
            db.query.return_value.filter.return_value.all.return_value = [inst1, inst2]
            db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [
                MagicMock() for _ in range(10)
            ]

            result = correlation_table()
            assert isinstance(result, str)
