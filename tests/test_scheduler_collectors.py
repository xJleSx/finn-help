from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.scheduler.collectors import collect_bond_offerings, collect_financial_reports


class TestCollectFinancialReports:
    def test_skip_non_stock_instruments(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        result = asyncio.run(collect_financial_reports(db))
        assert result is None

    def test_stores_new_report(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        db.query.return_value.filter.return_value.all.return_value = [inst]
        db.query.return_value.filter_by.return_value.first.return_value = None

        async def run():
            with patch("src.collectors.financials.FinancialReportCollector") as mock_cls:
                collector = AsyncMock()
                collector.fetch.return_value = {
                    "reporting_date": "2024-12-31",
                    "period_type": "FY",
                    "net_profit": 1500000000000.0,
                    "revenue": 3000000000000.0,
                    "roe": 25.0,
                }
                mock_cls.return_value = collector
                await collect_financial_reports(db)
                return collector
        collector = asyncio.run(run())
        collector.fetch.assert_called_once_with("SBER")
        added = db.add.call_args[0][0]
        assert added.instrument_id == 1
        assert added.report_date == date(2024, 12, 31)
        assert added.period_type == "FY"
        assert added.net_profit == 1500000000000.0

    def test_skips_existing_report(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        db.query.return_value.filter.return_value.all.return_value = [inst]
        existing = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = existing

        async def run():
            with patch("src.collectors.financials.FinancialReportCollector") as mock_cls:
                collector = AsyncMock()
                collector.fetch.return_value = {
                    "reporting_date": "2024-12-31",
                    "period_type": "FY",
                    "net_profit": 1500000000000.0,
                }
                mock_cls.return_value = collector
                await collect_financial_reports(db)
                return collector
        collector = asyncio.run(run())
        collector.fetch.assert_called_once_with("SBER")
        assert db.add.call_count == 0

    def test_skips_empty_fetch(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        db.query.return_value.filter.return_value.all.return_value = [inst]

        async def run():
            with patch("src.collectors.financials.FinancialReportCollector") as mock_cls:
                collector = AsyncMock()
                collector.fetch.return_value = {}
                mock_cls.return_value = collector
                await collect_financial_reports(db)
                return collector
        collector = asyncio.run(run())
        collector.fetch.assert_called_once_with("SBER")
        db.add.assert_not_called()


class TestCollectBondOfferings:
    def test_skip_non_bond_instruments(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        result = asyncio.run(collect_bond_offerings(db))
        assert result is None

    def test_stores_new_bond_offering(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SU26238RMFS5"
        db.query.return_value.filter.return_value.all.return_value = [inst]
        db.query.return_value.filter_by.return_value.first.return_value = None

        async def run():
            with patch("src.collectors.bonds.BondOfferingCollector") as mock_cls:
                collector = AsyncMock()
                collector.fetch_by_ticker.return_value = {
                    "isin": "RU000A101X55",
                    "offering_date": date(2023, 1, 15),
                    "coupon_type": "Fixed",
                    "coupon_rate": 8.5,
                    "coupon_period_days": 182,
                    "yield_to_maturity": 7.5,
                    "maturity_date": date(2028, 1, 15),
                    "credit_rating": "AAA",
                    "volume": 5000000000.0,
                    "has_amortization": False,
                    "has_offer": False,
                    "nominal_price": 1000.0,
                    "current_price_pct": 98.5,
                }
                mock_cls.return_value = collector
                await collect_bond_offerings(db)
                return collector
        collector = asyncio.run(run())
        collector.fetch_by_ticker.assert_called_once_with("SU26238RMFS5")
        added = db.add.call_args[0][0]
        assert added.instrument_id == 1
        assert added.isin == "RU000A101X55"
        assert added.coupon_rate == 8.5
        assert added.yield_to_maturity == 7.5

    def test_skips_offering_without_isin(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SU26238RMFS5"
        db.query.return_value.filter.return_value.all.return_value = [inst]

        async def run():
            with patch("src.collectors.bonds.BondOfferingCollector") as mock_cls:
                collector = AsyncMock()
                collector.fetch_by_ticker.return_value = {"ticker": "SU26238RMFS5"}
                mock_cls.return_value = collector
                await collect_bond_offerings(db)
                return collector
        collector = asyncio.run(run())
        collector.fetch_by_ticker.assert_called_once_with("SU26238RMFS5")
        db.add.assert_not_called()

    def test_skips_existing_bond(self):
        db = MagicMock()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SU26238RMFS5"
        db.query.return_value.filter.return_value.all.return_value = [inst]
        existing = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = existing

        async def run():
            with patch("src.collectors.bonds.BondOfferingCollector") as mock_cls:
                collector = AsyncMock()
                collector.fetch_by_ticker.return_value = {
                    "isin": "RU000A101X55",
                    "offering_date": date(2023, 1, 15),
                    "coupon_type": "Fixed",
                    "coupon_rate": 8.5,
                }
                mock_cls.return_value = collector
                await collect_bond_offerings(db)
                return collector
        collector = asyncio.run(run())
        collector.fetch_by_ticker.assert_called_once_with("SU26238RMFS5")
        db.add.assert_not_called()
