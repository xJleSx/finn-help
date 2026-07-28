from __future__ import annotations

from src.analysis.market.sector import SectorAnalyzer


class TestSectorAnalyzer:
    def test_init(self):
        analyzer = SectorAnalyzer()
        assert analyzer is not None

    def test_sector_for_finance(self):
        analyzer = SectorAnalyzer()
        assert analyzer.sector_for("Сбербанк", "SBER") == "Финансы"

    def test_sector_for_oil(self):
        analyzer = SectorAnalyzer()
        assert analyzer.sector_for("Газпром", "GAZP") == "Нефть"

    def test_sector_for_unknown(self):
        analyzer = SectorAnalyzer()
        assert analyzer.sector_for("Some Unknown Company", "UNKN") == "Прочее"

    def test_sector_for_empty_name(self):
        analyzer = SectorAnalyzer()
        assert analyzer.sector_for("", "TICK") == "Прочее"

    def test_sector_for_case_insensitive(self):
        analyzer = SectorAnalyzer()
        assert analyzer.sector_for("ЯНДЕКС", "YDX") == "IT"

    def test_sector_for_metals(self):
        analyzer = SectorAnalyzer()
        assert analyzer.sector_for("Норникель", "GMKN") == "Металлы"

    def test_sector_for_telecom(self):
        analyzer = SectorAnalyzer()
        assert analyzer.sector_for("МТС", "MTSS") == "Телеком"
