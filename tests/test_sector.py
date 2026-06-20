from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analysis.sector import sector_analyzer


class TestSectorFor:
    def test_bank(self):
        assert sector_analyzer.sector_for("Сбер Банк", "SBER") == "Финансы"

    def test_oil(self):
        assert sector_analyzer.sector_for("Газпром", "GAZP") == "Нефть"

    def test_it(self):
        assert sector_analyzer.sector_for("Яндекс", "YNDX") == "IT"

    def test_other(self):
        assert sector_analyzer.sector_for("Unknown Corp", "UNK") == "Прочее"

    def test_from_name(self):
        assert sector_analyzer.sector_for("Газпром нефть", "GAZP") == "Нефть"

    def test_metal(self):
        assert sector_analyzer.sector_for("Норникель", "GMKN") == "Металлы"

    def test_telecom(self):
        assert sector_analyzer.sector_for("МТС", "MTSS") == "Телеком"


class TestSectorPerformance:
    def test_no_instruments(self):
        db = MagicMock()
        db.query.return_value.all.return_value = []
        result = sector_analyzer.compute_sector_performance(db, days=30)
        assert result == {}

    def test_skips_instruments_without_prices(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.full_name = "Сбер"
        inst.ticker = "SBER"
        db.query.return_value.all.return_value = [inst]
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = sector_analyzer.compute_sector_performance(db)
        assert result == {}

    def test_with_valid_data(self):
        db = MagicMock()
        inst1 = MagicMock()
        inst1.id = 1
        inst1.full_name = "Сбер Банк"
        inst1.ticker = "SBER"
        inst2 = MagicMock()
        inst2.id = 2
        inst2.full_name = "ВТБ Банк"
        inst2.ticker = "VTBR"
        db.query.return_value.all.return_value = [inst1, inst2]

        first1, last1 = MagicMock(), MagicMock()
        first1.close = 100.0
        last1.close = 110.0
        first2, last2 = MagicMock(), MagicMock()
        first2.close = 50.0
        last2.close = 55.0

        db.query.return_value.filter.return_value.order_by.return_value.first.side_effect = [first1, last1, first2, last2]

        result = sector_analyzer.compute_sector_performance(db, days=30)
        assert "Финансы" in result
        assert result["Финансы"] == pytest.approx(0.1, rel=0.01)


class TestSectorVolatility:
    def test_no_data(self):
        db = MagicMock()
        db.query.return_value.all.return_value = []
        result = sector_analyzer.compute_sector_volatility(db)
        assert result == {}

    def test_fewer_than_10_prices(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.full_name = "Сбер"
        inst.ticker = "SBER"
        db.query.return_value.all.return_value = [inst]
        prices = [MagicMock() for _ in range(5)]
        for p in prices:
            p.close = 100.0
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = prices

        result = sector_analyzer.compute_sector_volatility(db)
        assert result == {}


class TestSectorCorrelation:
    def test_no_data(self):
        db = MagicMock()
        db.query.return_value.all.return_value = []
        result = sector_analyzer.compute_sector_correlation(db)
        assert result == {}

    def test_single_sector(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.full_name = "Сбер"
        inst.ticker = "SBER"
        db.query.return_value.all.return_value = [inst]
        prices = [MagicMock() for _ in range(30)]
        for p in prices:
            p.close = 100.0
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = prices

        result = sector_analyzer.compute_sector_correlation(db)
        assert "Финансы" in result
