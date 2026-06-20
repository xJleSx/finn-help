from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analysis.whatif import _find_correlated, whatif_macro, whatif_scenario


class TestWhatIfScenario:
    def test_instrument_not_found(self):
        with patch("src.analysis.whatif.get_session") as mock_gs:
            db = MagicMock()
            mock_gs.return_value = db
            db.query.return_value.filter_by.return_value.first.return_value = None
            result = whatif_scenario("UNKNOWN", -0.1)
            assert "не найден" in result
            db.close.assert_called_once()

    def test_no_price(self):
        with patch("src.analysis.whatif.get_session") as mock_gs:
            db = MagicMock()
            inst = MagicMock()
            inst.id = 42
            price_entry = MagicMock()
            price_entry.close = None
            db.query.return_value.filter_by.return_value.first.side_effect = [inst]
            db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price_entry
            mock_gs.return_value = db
            result = whatif_scenario("SBER", -0.1)
            assert "Нет цены" in result
            db.close.assert_called_once()

    def test_successful_scenario(self):
        with (
            patch("src.analysis.whatif.get_session") as mock_gs,
            patch("src.analysis.whatif._find_correlated", return_value=[]),
        ):
            db = MagicMock()
            inst = MagicMock()
            inst.id = 42
            price_entry = MagicMock()
            price_entry.close = 250.0
            db.query.return_value.filter_by.return_value.first.side_effect = [inst]
            db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price_entry
            mock_gs.return_value = db
            result = whatif_scenario("SBER", -0.1)
            assert "What-If" in result
            assert "SBER" in result
            db.close.assert_called_once()


class TestWhatIfMacro:
    def test_unknown_shock(self):
        result = whatif_macro("unknown")
        assert "Неизвестный" in result

    def test_known_shock(self):
        result = whatif_macro("oil40")
        assert "Нефть" in result

    def test_with_sector_impacts(self):
        result = whatif_macro("rate25")
        assert "Банки" in result

    def test_covid_scenario(self):
        result = whatif_macro("covid2020")
        assert "COVID" in result

    def test_sanctions_scenario(self):
        result = whatif_macro("sanctions2022")
        assert "Санкции" in result

    def test_ruble_scenario(self):
        result = whatif_macro("rubdown20")
        assert "Рубль" in result or "Потреб" in result


class TestFindCorrelated:
    def test_no_instrument(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        assert _find_correlated(db, "UNKNOWN") == []

    def test_fewer_than_30_prices(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        db.query.return_value.filter_by.return_value.first.return_value = inst
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [MagicMock() for _ in range(10)]
        assert _find_correlated(db, "SBER") == []

    def test_returns_related_tickers(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        db.query.return_value.filter_by.return_value.first.return_value = inst
        ticker_prices = []
        for i in range(30):
            p = MagicMock()
            p.close = 100.0 + i
            ticker_prices.append(p)
        other_prices = []
        for i in range(30):
            p = MagicMock()
            p.close = 110.0 + i * 0.5
            other_prices.append(p)
        db.query.return_value.filter_by.return_value.order_by.return_value.all.side_effect = [
            ticker_prices, other_prices
        ]
        other = MagicMock()
        other.id = 2
        other.ticker = "GAZP"
        db.query.return_value.filter.return_value.limit.return_value.all.return_value = [other]

        result = _find_correlated(db, "SBER")
        assert len(result) > 0
        assert result[0][0] == "GAZP"
