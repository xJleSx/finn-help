from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock

from src.collectors.bonds import BondOfferingCollector


class TestBondOfferingCollector:
    def test_fetch_by_ticker_empty_when_no_isin(self):
        async def run():
            moex = AsyncMock()
            moex.get_security_info.return_value = {}
            collector = BondOfferingCollector()
            collector._get_moex = AsyncMock(return_value=moex)
            return await collector.fetch_by_ticker("SU26238RMFS5")
        result = asyncio.run(run())
        assert result == {}

    def test_fetch_by_ticker_basic_info(self):
        async def run():
            moex = AsyncMock()
            moex.get_security_info.return_value = {
                "isin": "RU000A101X55",
                "face_value": 1000.0,
                "issue_date": "2023-01-15",
            }
            moex.get_security_description.return_value = [
                {"name": "MATURITYDATE", "value": "2028-01-15"},
                {"name": "COUPONPERCENT", "value": "8.5"},
                {"name": "COUPONPERIOD", "value": "182"},
                {"name": "COUPONTYPE", "value": "Fixed"},
                {"name": "CREDITRATING", "value": "AAA"},
                {"name": "ISSUESIZE", "value": "5000000000"},
            ]
            moex.get_marketdata.return_value = {"YIELD": 7.5, "LAST": 98.5}
            collector = BondOfferingCollector()
            collector._get_moex = AsyncMock(return_value=moex)
            return await collector.fetch_by_ticker("SU26238RMFS5")
        result = asyncio.run(run())
        assert result["isin"] == "RU000A101X55"
        assert result["nominal_price"] == 1000.0
        assert result["offering_date"] == date(2023, 1, 15)
        assert result["maturity_date"] == date(2028, 1, 15)
        assert result["coupon_rate"] == 8.5
        assert result["coupon_period_days"] == 182
        assert result["coupon_type"] == "Fixed"
        assert result["credit_rating"] == "AAA"
        assert result["volume"] == 5000000000.0
        assert result["yield_to_maturity"] == 7.5
        assert result["current_price_pct"] == 98.5
        assert result["has_amortization"] is False
        assert result["has_offer"] is False

    def test_fetch_by_ticker_with_amortization_and_offer(self):
        async def run():
            moex = AsyncMock()
            moex.get_security_info.return_value = {
                "isin": "RU000A101X55",
                "face_value": 1000.0,
                "issue_date": "2023-01-15",
            }
            moex.get_security_description.return_value = [
                {"name": "AMORTIZATION", "value": "yes"},
                {"name": "OFFERDATE", "value": "2025-01-15"},
                {"name": "MATURITYDATE", "value": "2028-01-15"},
                {"name": "COUPONTYPE", "value": "Float"},
            ]
            moex.get_marketdata.return_value = {}
            collector = BondOfferingCollector()
            collector._get_moex = AsyncMock(return_value=moex)
            return await collector.fetch_by_ticker("SU26238RMFS5")
        result = asyncio.run(run())
        assert result["has_amortization"] is True
        assert result["has_offer"] is True

    def test_fetch_by_ticker_marketdata_missing(self):
        async def run():
            moex = AsyncMock()
            moex.get_security_info.return_value = {
                "isin": "RU000A101X55",
                "face_value": 1000.0,
                "issue_date": "2023-01-15",
            }
            moex.get_security_description.return_value = []
            moex.get_marketdata.return_value = {}
            collector = BondOfferingCollector()
            collector._get_moex = AsyncMock(return_value=moex)
            return await collector.fetch_by_ticker("SU26238RMFS5")
        result = asyncio.run(run())
        assert result["isin"] == "RU000A101X55"
        assert result.get("yield_to_maturity") is None
        assert result.get("current_price_pct") is None

    def test_fetch_all_empty(self):
        async def run():
            moex = AsyncMock()
            moex.get_bonds.return_value = []
            collector = BondOfferingCollector()
            collector._get_moex = AsyncMock(return_value=moex)
            return await collector.fetch_all()
        result = asyncio.run(run())
        assert result == []

    def test_fetch_all_skips_bonds_without_secid(self):
        async def run():
            moex = AsyncMock()
            moex.get_bonds.return_value = [{"SECID": None}]
            collector = BondOfferingCollector()
            collector._get_moex = AsyncMock(return_value=moex)
            return await collector.fetch_all()
        result = asyncio.run(run())
        assert result == []

    def test_close(self):
        async def run():
            moex = AsyncMock()
            collector = BondOfferingCollector()
            collector._moex = moex
            await collector.close()
            moex.__aexit__.assert_called_once()
        asyncio.run(run())

    def test_parse_date_none(self):
        from src.collectors.bonds import _parse_date
        assert _parse_date(None) is None

    def test_parse_date_empty_string(self):
        from src.collectors.bonds import _parse_date
        assert _parse_date("") is None

    def test_parse_date_iso(self):
        from src.collectors.bonds import _parse_date
        assert _parse_date("2023-06-15") == date(2023, 6, 15)

    def test_parse_date_date_obj(self):
        from src.collectors.bonds import _parse_date
        d = date(2023, 6, 15)
        assert _parse_date(d) == d
