"""Tests for MOEXCollector"""

from __future__ import annotations

import re

import pytest


class TestBoardMap:
    def test_board_map_stock(self):
        from src.collectors.moex import BOARD_MAP

        assert BOARD_MAP["stock"] == "/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"

    def test_board_map_etf(self):
        from src.collectors.moex import BOARD_MAP

        assert BOARD_MAP["etf"] == "/history/engines/stock/markets/shares/boards/TQTF/securities/{ticker}.json"

    def test_board_map_bond(self):
        from src.collectors.moex import BOARD_MAP

        assert BOARD_MAP["bond"] == "/history/engines/stock/markets/bonds/boards/TQCB/securities/{ticker}.json"

    def test_board_map_shares(self):
        from src.collectors.moex import BOARD_MAP

        assert "shares" in BOARD_MAP


class TestMOEXCollectorUnit:
    """Unit tests with mocked HTTP"""

    @pytest.fixture
    def collector(self):
        from src.collectors.moex import MOEXCollector

        return MOEXCollector()

    @pytest.mark.asyncio
    async def test_get_securities_parses_columns(self, collector, httpx_mock):
        httpx_mock.add_response(
            url="https://iss.moex.com/iss/securities.json?iss.meta=off",
            json={
                "securities": {
                    "columns": ["SECID", "SHORTNAME"],
                    "data": [["SBER", "Сбер"]],
                }
            },
        )
        result = await collector.get_securities()
        assert result == [{"SECID": "SBER", "SHORTNAME": "Сбер"}]

    @pytest.mark.asyncio
    async def test_get_securities_empty_response(self, collector, httpx_mock):
        httpx_mock.add_response(
            url="https://iss.moex.com/iss/securities.json?iss.meta=off",
            json={},
        )
        result = await collector.get_securities()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_stocks_uses_correct_board(self, collector, httpx_mock):
        httpx_mock.add_response(
            url="https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json?iss.meta=off",
            json={"securities": {"columns": ["SECID"], "data": [["SBER"], ["GAZP"]]}},
        )
        result = await collector.get_stocks()
        assert len(result) == 2
        assert result[0]["SECID"] == "SBER"

    @pytest.mark.asyncio
    async def test_get_etfs_uses_correct_board(self, collector, httpx_mock):
        httpx_mock.add_response(
            url="https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQTF/securities.json?iss.meta=off",
            json={"securities": {"columns": ["SECID"], "data": [["FXRL"], ["SBMX"]]}},
        )
        result = await collector.get_etfs()
        assert len(result) == 2
        assert result[0]["SECID"] == "FXRL"

    @pytest.mark.asyncio
    async def test_get_history_with_board_stock(self, collector, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/history/engines/stock/markets/shares/boards/TQBR/securities/SBER.json.*"),
            json={
                "history": {
                    "columns": ["TRADEDATE", "CLOSE", "VOLUME"],
                    "data": [["2025-06-01", 300.0, 1000000]],
                }
            },
        )
        result = await collector.get_history("SBER", from_date="2025-01-01", board="stock")
        assert len(result) == 1
        assert result[0]["CLOSE"] == 300.0

    @pytest.mark.asyncio
    async def test_get_history_with_board_etf(self, collector, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/history/engines/stock/markets/shares/boards/TQTF/securities/FXRL.json.*"),
            json={
                "history": {
                    "columns": ["TRADEDATE", "CLOSE"],
                    "data": [["2025-06-01", 150.0]],
                }
            },
        )
        result = await collector.get_history("FXRL", from_date="2025-01-01", board="etf")
        assert len(result) == 1
        assert result[0]["CLOSE"] == 150.0

    @pytest.mark.asyncio
    async def test_get_history_with_board_bond(self, collector, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(
                r".*/history/engines/stock/markets/bonds/boards/(TQCB|TQBD|TQOB)/securities/SU26238RMFS5.json.*"
            ),
            json={
                "history": {
                    "columns": ["TRADEDATE", "CLOSE"],
                    "data": [["2025-06-01", 95.0]],
                }
            },
        )
        result = await collector.get_history("SU26238RMFS5", from_date="2025-01-01", board="bond")
        assert len(result) == 1
        assert result[0]["CLOSE"] == 95.0

    @pytest.mark.asyncio
    async def test_get_history_fallback_to_shares(self, collector, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/history/engines/stock/markets/shares/securities/TEST.json.*"),
            json={
                "history": {
                    "columns": ["TRADEDATE", "CLOSE"],
                    "data": [["2025-06-01", 100.0]],
                }
            },
        )
        result = await collector.get_history("TEST", from_date="2025-01-01", board="unknown")
        assert result[0]["CLOSE"] == 100.0

    @pytest.mark.asyncio
    async def test_get_history_default_dates(self, collector, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/history/engines/stock/markets/shares/securities/SBER.json.*"),
            json={"history": {"columns": ["TRADEDATE"], "data": []}},
        )
        result = await collector.get_history("SBER", board="shares")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_bonds_parses_columns(self, collector, httpx_mock):
        for board in ["TQCB", "TQBD", "TQOB"]:
            httpx_mock.add_response(
                url=f"https://iss.moex.com/iss/engines/stock/markets/bonds/boards/{board}/securities.json?iss.meta=off",
                json={
                    "securities": {
                        "columns": ["SECID", "SHORTNAME"],
                        "data": [["SU26238RMFS5", "ОФЗ 26238"]] if board == "TQCB" else [],
                    }
                },
                is_optional=board != "TQCB",
            )
        result = await collector.get_bonds()
        assert len(result) == 1
        assert result[0]["SECID"] == "SU26238RMFS5"

    @pytest.mark.asyncio
    async def test_get_dividends(self, collector, httpx_mock):
        httpx_mock.add_response(
            url="https://iss.moex.com/iss/securities/SBER/dividends.json?iss.meta=off",
            json={
                "dividends": {
                    "columns": ["recordDate", "value"],
                    "data": [["2025-07-01", 33.0]],
                }
            },
        )
        result = await collector.get_dividends("SBER")
        assert len(result) == 1
        assert result[0]["value"] == 33.0

    @pytest.mark.asyncio
    async def test_get_marketdata(self, collector, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/engines/stock/markets/shares/securities/SBER.json.*"),
            json={
                "marketdata": {
                    "columns": ["SECID", "SHORTNAME", "LOTSIZE"],
                    "data": [["SBER", "Сбер Банк", 10]],
                }
            },
        )
        result = await collector.get_marketdata("SBER")
        assert result["SECID"] == "SBER"
        assert result["LOTSIZE"] == 10

    @pytest.mark.asyncio
    async def test_get_marketdata_empty(self, collector, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/engines/stock/markets/shares/securities/NONEXISTENT.json.*"),
            json={
                "marketdata": {
                    "columns": ["SECID"],
                    "data": [],
                }
            },
        )
        result = await collector.get_marketdata("NONEXISTENT")
        assert result == {}
