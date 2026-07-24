from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.scheduler.collectors import collect_bond_offerings, collect_financial_reports


class TestCollectFinancialReports:
    def _make_async_db(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result
        return db

    def test_skip_non_stock_instruments(self):
        db = self._make_async_db()
        result = asyncio.run(collect_financial_reports(db))
        assert result is None

    def test_stores_new_report(self):
        db = self._make_async_db()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        db.execute.return_value.scalars.return_value.all.return_value = [inst]

        collector = AsyncMock()
        collector.fetch.return_value = {
            "reporting_date": "2024-12-31",
            "period_type": "FY",
            "net_profit": 1500000000000.0,
            "revenue": 3000000000000.0,
            "roe": 25.0,
        }

        with patch("src.collectors.financials.FinancialReportCollector", return_value=collector):
            asyncio.run(collect_financial_reports(db))

        collector.fetch.assert_called_once_with("SBER")

    def test_skips_existing_report(self):
        db = self._make_async_db()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        existing = MagicMock(instrument_id=1, report_date=date(2024, 12, 31), period_type="FY")
        db.execute.return_value.scalars.return_value.all.side_effect = [[inst], [existing]]

        collector = AsyncMock()
        collector.fetch.return_value = {
            "reporting_date": "2024-12-31",
            "period_type": "FY",
            "net_profit": 1500000000000.0,
        }

        with patch("src.collectors.financials.FinancialReportCollector", return_value=collector):
            asyncio.run(collect_financial_reports(db))

        collector.fetch.assert_called_once_with("SBER")
        assert db.add.call_count == 0

    def test_skips_empty_fetch(self):
        db = self._make_async_db()
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SBER"
        db.execute.return_value.scalars.return_value.all.return_value = [inst]

        collector = AsyncMock()
        collector.fetch.return_value = {}

        with patch("src.collectors.financials.FinancialReportCollector", return_value=collector):
            asyncio.run(collect_financial_reports(db))

        collector.fetch.assert_called_once_with("SBER")
        db.add.assert_not_called()


class TestCollectBondOfferings:
    def _make_async_db(self, scalars_return=None):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = scalars_return or []
        db.execute.return_value = mock_result
        return db

    def test_skip_non_bond_instruments(self):
        db = self._make_async_db()
        result = asyncio.run(collect_bond_offerings(db))
        assert result is None

    def test_stores_new_bond_offering(self):
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SU26238RMFS5"
        db = self._make_async_db(scalars_return=[inst])

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

        with patch("src.collectors.bonds.BondOfferingCollector", return_value=collector):
            asyncio.run(collect_bond_offerings(db))

        collector.fetch_by_ticker.assert_called_once_with("SU26238RMFS5")
        added = db.add.call_args[0][0]
        assert added.instrument_id == 1
        assert added.isin == "RU000A101X55"
        assert added.coupon_rate == 8.5
        assert added.yield_to_maturity == 7.5

    def test_skips_offering_without_isin(self):
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SU26238RMFS5"
        db = self._make_async_db(scalars_return=[inst])

        collector = AsyncMock()
        collector.fetch_by_ticker.return_value = {"ticker": "SU26238RMFS5"}

        with patch("src.collectors.bonds.BondOfferingCollector", return_value=collector):
            asyncio.run(collect_bond_offerings(db))

        collector.fetch_by_ticker.assert_called_once_with("SU26238RMFS5")
        db.add.assert_not_called()

    def test_skips_existing_bond(self):
        inst = MagicMock()
        inst.id = 1
        inst.ticker = "SU26238RMFS5"
        existing = MagicMock(instrument_id=1, isin="RU000A101X55")
        db = AsyncMock()
        mock_result_1 = MagicMock()
        mock_result_1.scalars.return_value.all.return_value = [inst]
        mock_result_2 = MagicMock()
        mock_result_2.scalars.return_value.all.return_value = [existing]
        db.execute.side_effect = [mock_result_1, mock_result_2]

        collector = AsyncMock()
        collector.fetch_by_ticker.return_value = {
            "isin": "RU000A101X55",
            "offering_date": date(2023, 1, 15),
            "coupon_type": "Fixed",
            "coupon_rate": 8.5,
        }

        with patch("src.collectors.bonds.BondOfferingCollector", return_value=collector):
            asyncio.run(collect_bond_offerings(db))

        collector.fetch_by_ticker.assert_called_once_with("SU26238RMFS5")
        db.add.assert_not_called()
