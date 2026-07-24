from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from src.analysis.bonds.new_bond_locator import (
    _extract_company_name,
    _is_recently_issued,
    _paid_coupon_count,
    _parse_coupon_date,
    _rating_score,
    _safe_float,
    _safe_int,
    discover_new_bonds,
    find_new_bonds,
)


class TestRatingScore:
    def test_aaa_returns_7(self):
        assert _rating_score("AAA") == 7

    def test_bbb_minus_returns_minus_2(self):
        assert _rating_score("BBB-") == -2

    def test_unknown_rating_returns_minus_999(self):
        assert _rating_score("UNKNOWN") == -999

    def test_none_returns_minus_999(self):
        assert _rating_score(None) == -999

    def test_case_insensitive(self):
        assert _rating_score("aaa") == 7
        assert _rating_score("Aaa") == 7

    def test_extra_whitespace(self):
        assert _rating_score("  AA+  ") == 6


class TestParseCouponDate:
    def test_parses_iso_string(self):
        assert _parse_coupon_date("2024-06-15") == date(2024, 6, 15)

    def test_handles_datetime_object(self):
        d = date(2024, 6, 15)
        assert _parse_coupon_date(d) == d

    def test_returns_none_for_none(self):
        assert _parse_coupon_date(None) is None

    def test_returns_none_for_invalid_string(self):
        assert _parse_coupon_date("not-a-date") is None

    def test_truncates_datetime_iso(self):
        assert _parse_coupon_date("2024-06-15T12:00:00") == date(2024, 6, 15)


class TestSafeInt:
    def test_converts_valid(self):
        assert _safe_int("42") == 42
        assert _safe_int(42) == 42

    def test_returns_none_for_none(self):
        assert _safe_int(None) is None

    def test_returns_none_for_invalid(self):
        assert _safe_int("abc") is None


class TestSafeFloat:
    def test_converts_valid(self):
        assert _safe_float("3.14") == 3.14
        assert _safe_float(3.14) == 3.14

    def test_returns_none_for_none(self):
        assert _safe_float(None) is None

    def test_returns_none_for_invalid(self):
        assert _safe_float("abc") is None


class TestExtractCompanyName:
    def test_strips_series_suffix(self):
        assert _extract_company_name("Газпром 001P-02") == "Газпром"

    def test_strips_bond_type_words(self):
        assert _extract_company_name("Сбербанк облигация") == "Сбербанк"

    def test_truncates_to_30_chars(self):
        name = _extract_company_name("A" * 50)
        assert len(name) <= 30

    def test_returns_empty_for_blank(self):
        assert _extract_company_name("") == ""
        assert _extract_company_name("   ") == ""


class TestPaidCouponCount:
    def test_counts_paid_coupons(self):
        schedules = [
            MagicMock(coupon_number=1, paid=True, coupon_date=date.today()),
            MagicMock(coupon_number=2, paid=False, coupon_date=date.today() - timedelta(days=10)),
        ]
        assert _paid_coupon_count(schedules) == 2

    def test_ignores_non_positive_coupon_numbers(self):
        schedules = [
            MagicMock(coupon_number=0, paid=True, coupon_date=date.today()),
            MagicMock(coupon_number=-1, paid=True, coupon_date=date.today()),
        ]
        assert _paid_coupon_count(schedules) == 0

    def test_counts_future_dates_as_not_paid(self):
        schedules = [
            MagicMock(coupon_number=1, paid=False, coupon_date=date.today() + timedelta(days=30)),
        ]
        assert _paid_coupon_count(schedules) == 0

    def test_empty_schedule_returns_0(self):
        assert _paid_coupon_count([]) == 0


class TestIsRecentlyIssued:
    def test_true_when_2_or_fewer_paid(self):
        with patch("src.analysis.bonds.new_bond_locator._paid_coupon_count", return_value=2):
            assert _is_recently_issued([]) is True

    def test_false_when_more_than_2_paid(self):
        with patch("src.analysis.bonds.new_bond_locator._paid_coupon_count", return_value=3):
            assert _is_recently_issued([]) is False


class TestFindNewBonds:
    @patch("src.analysis.bonds.new_bond_locator.joinedload")
    @patch("src.analysis.bonds.new_bond_locator.Instrument")
    def test_returns_empty_when_no_bonds(self, mock_instr, mock_jl):
        mock_db = MagicMock()
        mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = []
        result = find_new_bonds(mock_db)
        assert result == []

    @patch("src.analysis.bonds.new_bond_locator.joinedload")
    @patch("src.analysis.bonds.new_bond_locator.Instrument")
    def test_skips_instruments_without_offerings(self, mock_instr, mock_jl):
        mock_db = MagicMock()
        inst = MagicMock()
        inst.bond_offerings = []
        inst.coupon_schedule = []
        mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = [inst]
        result = find_new_bonds(mock_db)
        assert result == []

    @patch("src.analysis.bonds.new_bond_locator.joinedload")
    @patch("src.analysis.bonds.new_bond_locator.Instrument")
    def test_skips_bonds_with_many_paid_coupons(self, mock_instr, mock_jl):
        mock_db = MagicMock()
        offering = MagicMock()
        offering.offering_date = date.today() - timedelta(days=10)
        offering.yield_to_maturity = 8.0
        offering.credit_rating = "AAA"
        offering.coupon_rate = 7.5
        offering.coupon_type = "fixed"
        offering.coupon_period_days = 182
        offering.current_price_pct = 100.0
        offering.maturity_date = date.today() + timedelta(days=365)
        offering.nominal_price = 1000.0
        offering.has_amortization = False
        offering.has_offer = False
        offering.isin = "RU000A"
        offering.extra = {"company_name": "Test Corp"}

        inst = MagicMock()
        inst.ticker = "RU000B"
        inst.full_name = "Test Corp BO-01"
        inst.isin = "RU000A"
        inst.bond_offerings = [offering]
        inst.coupon_schedule = [MagicMock(coupon_number=i, paid=True, coupon_date=date.today()) for i in range(3, 10)]

        mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = [inst]
        result = find_new_bonds(mock_db)
        assert result == []

    @patch("src.analysis.bonds.new_bond_locator.joinedload")
    @patch("src.analysis.bonds.new_bond_locator.Instrument")
    def test_filters_by_min_ytm(self, mock_instr, mock_jl):
        mock_db = MagicMock()
        offering = MagicMock()
        offering.offering_date = date.today() - timedelta(days=10)
        offering.yield_to_maturity = 5.0
        offering.credit_rating = "AAA"
        offering.coupon_rate = 6.0
        offering.coupon_type = "fixed"
        offering.coupon_period_days = 182
        offering.current_price_pct = 100.0
        offering.maturity_date = date.today() + timedelta(days=365)
        offering.nominal_price = 1000.0
        offering.has_amortization = False
        offering.has_offer = False
        offering.isin = "RU000A"
        offering.extra = {}

        inst = MagicMock()
        inst.ticker = "RU000B"
        inst.full_name = "Test Corp"
        inst.isin = "RU000A"
        inst.bond_offerings = [offering]
        inst.coupon_schedule = [MagicMock(coupon_number=1, paid=False, coupon_date=date.today() + timedelta(days=60))]

        mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = [inst]
        result = find_new_bonds(mock_db, min_ytm=6.0)
        assert result == []

    @patch("src.analysis.bonds.new_bond_locator.joinedload")
    @patch("src.analysis.bonds.new_bond_locator.Instrument")
    def test_sorts_by_rating_then_ytm(self, mock_instr, mock_jl):
        mock_db = MagicMock()

        def make_bond(ticker, rating, ytm, offering_date_ago=10):
            offering = MagicMock()
            offering.offering_date = date.today() - timedelta(days=offering_date_ago)
            offering.yield_to_maturity = ytm
            offering.credit_rating = rating
            offering.coupon_rate = 7.0
            offering.coupon_type = "fixed"
            offering.coupon_period_days = 182
            offering.current_price_pct = 100.0
            offering.maturity_date = date.today() + timedelta(days=365)
            offering.nominal_price = 1000.0
            offering.has_amortization = False
            offering.has_offer = False
            offering.isin = f"ISIN{ticker}"
            offering.extra = {"company_name": f"Company {ticker}"}
            inst = MagicMock()
            inst.ticker = ticker
            inst.full_name = f"Bond {ticker}"
            inst.isin = f"ISIN{ticker}"
            inst.bond_offerings = [offering]
            inst.coupon_schedule = [MagicMock(coupon_number=1, paid=False, coupon_date=date.today() + timedelta(days=60))]
            return inst

        inst_a = make_bond("BOND_A", "AAA", 7.0)
        inst_b = make_bond("BOND_B", "BBB", 9.0)
        inst_c = make_bond("BOND_C", "AA", 8.0)

        mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = [inst_a, inst_b, inst_c]
        result = find_new_bonds(mock_db, max_results=10)
        assert len(result) == 3
        assert result[0]["ticker"] == "BOND_A"
        assert result[1]["ticker"] == "BOND_C"
        assert result[2]["ticker"] == "BOND_B"

    @patch("src.analysis.bonds.new_bond_locator.joinedload")
    @patch("src.analysis.bonds.new_bond_locator.Instrument")
    def test_filters_by_min_days_to_first_coupon(self, mock_instr, mock_jl):
        mock_db = MagicMock()
        offering = MagicMock()
        offering.offering_date = date.today() - timedelta(days=10)
        offering.yield_to_maturity = 8.0
        offering.credit_rating = "AAA"
        offering.coupon_rate = 7.5
        offering.coupon_type = "fixed"
        offering.coupon_period_days = 182
        offering.current_price_pct = 100.0
        offering.maturity_date = date.today() + timedelta(days=365)
        offering.nominal_price = 1000.0
        offering.has_amortization = False
        offering.has_offer = False
        offering.isin = "RU000A"
        offering.extra = {}

        inst = MagicMock()
        inst.ticker = "RU000B"
        inst.full_name = "Test Corp"
        inst.isin = "RU000A"
        inst.bond_offerings = [offering]
        inst.coupon_schedule = [MagicMock(coupon_number=1, paid=False, coupon_date=date.today() + timedelta(days=5))]

        mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = [inst]
        result = find_new_bonds(mock_db, min_days_to_first_coupon=10)
        assert result == []

    @patch("src.analysis.bonds.new_bond_locator.joinedload")
    @patch("src.analysis.bonds.new_bond_locator.Instrument")
    def test_respects_max_results(self, mock_instr, mock_jl):
        mock_db = MagicMock()
        bonds = []
        for i in range(10):
            offering = MagicMock()
            offering.offering_date = date.today() - timedelta(days=10)
            offering.yield_to_maturity = float(5 + i)
            offering.credit_rating = "A"
            offering.coupon_rate = 6.0
            offering.coupon_type = "fixed"
            offering.coupon_period_days = 182
            offering.current_price_pct = 100.0
            offering.maturity_date = date.today() + timedelta(days=365)
            offering.nominal_price = 1000.0
            offering.has_amortization = False
            offering.has_offer = False
            offering.isin = f"ISIN{i}"
            offering.extra = {"company_name": f"Company {i}"}
            inst = MagicMock()
            inst.ticker = f"BOND_{i}"
            inst.full_name = f"Bond {i}"
            inst.isin = f"ISIN{i}"
            inst.bond_offerings = [offering]
            inst.coupon_schedule = [MagicMock(coupon_number=1, paid=False, coupon_date=date.today() + timedelta(days=60))]
            bonds.append(inst)

        mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = bonds
        result = find_new_bonds(mock_db, max_results=3)
        assert len(result) == 3


class TestDiscoverNewBonds:
    @patch("src.collectors.moex.MOEXCollector")
    @patch("src.collectors.bonds.BondOfferingCollector")
    async def test_falls_through_to_find_new_bonds_when_no_recent_moex(
        self, mock_bond_collector, mock_moex_collector, mock_db
    ):
        mock_moex_instance = AsyncMock()
        mock_moex_instance.get_bonds = AsyncMock(return_value=[])
        mock_moex_collector.return_value = mock_moex_instance
        mock_bond_collector.return_value = AsyncMock()

        with patch("src.analysis.bonds.new_bond_locator.find_new_bonds") as mock_find:
            mock_find.return_value = [{"ticker": "RU000B"}]
            with patch("src.db.connection.get_session") as mock_get_session:
                mock_get_session.return_value.__enter__.return_value = MagicMock()
                result = await discover_new_bonds(mock_db)
                assert result == [{"ticker": "RU000B"}]

    @patch("src.collectors.moex.MOEXCollector")
    @patch("src.collectors.bonds.BondOfferingCollector")
    async def test_aborts_when_offering_missing_isin(
        self, mock_bond_collector, mock_moex_collector, mock_db
    ):
        mock_moex_instance = AsyncMock()
        mock_moex_instance.get_bonds = AsyncMock(return_value=[
            {"SECID": "RU000A", "SHORTNAME": "Test", "ISSUEDATE": date.today().isoformat()},
        ])
        mock_moex_collector.return_value = mock_moex_instance

        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        mock_collector_instance = AsyncMock()
        mock_collector_instance.fetch_by_ticker = AsyncMock(return_value={"isin": None})
        mock_bond_collector.return_value = mock_collector_instance

        with patch("src.analysis.bonds.new_bond_locator.find_new_bonds") as mock_find:
            mock_find.return_value = []
            with patch("src.db.connection.get_session") as mock_get_session:
                mock_get_session.return_value.__enter__.return_value = MagicMock()
                result = await discover_new_bonds(mock_db)
                assert result == []

    @patch("src.collectors.moex.MOEXCollector")
    @patch("src.collectors.bonds.BondOfferingCollector")
    async def test_adds_new_bond_to_db(
        self, mock_bond_collector, mock_moex_collector, mock_db
    ):
        mock_moex_instance = AsyncMock()
        mock_moex_instance.get_bonds = AsyncMock(return_value=[
            {"SECID": "RU000A", "SHORTNAME": "Test Bond", "ISSUEDATE": date.today().isoformat()},
        ])
        mock_moex_collector.return_value = mock_moex_instance

        mock_db.execute = AsyncMock()
        mock_db.add = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        mock_collector_instance = AsyncMock()
        mock_collector_instance.fetch_by_ticker = AsyncMock(return_value={
            "isin": "RU000A12345",
            "full_name": "Test Corp Bond",
            "short_name": "Test Bond",
            "offering_date": date.today(),
            "coupon_type": "fixed",
            "coupon_rate": 8.0,
            "coupon_period_days": 182,
            "yield_to_maturity": 7.5,
            "maturity_date": date.today() + timedelta(days=3650),
            "credit_rating": "AAA",
            "nominal_price": 1000.0,
            "coupon_schedule": [
                {"coupondate": (date.today() + timedelta(days=60)).isoformat(), "value": 40.0,
                 "couponnumber": 1, "currency": "RUB"},
            ],
            "company_name": "Test Corp",
            "emitter_id": 123,
        })
        mock_bond_collector.return_value = mock_collector_instance

        with patch("src.analysis.bonds.new_bond_locator.find_new_bonds") as mock_find:
            mock_find.return_value = [{"ticker": "RU000A", "isin": "RU000A12345"}]
            with patch("src.db.connection.get_session") as mock_get_session:
                mock_get_session.return_value.__enter__.return_value = MagicMock()
                result = await discover_new_bonds(mock_db)

                mock_db.add.assert_any_call(ANY)
                mock_db.flush.assert_called()
                mock_db.commit.assert_called()
                assert result == [{"ticker": "RU000A", "isin": "RU000A12345"}]

    @patch("src.collectors.moex.MOEXCollector")
    @patch("src.collectors.bonds.BondOfferingCollector")
    async def test_skips_missing_offering_date(
        self, mock_bond_collector, mock_moex_collector, mock_db
    ):
        mock_moex_instance = AsyncMock()
        mock_moex_instance.get_bonds = AsyncMock(return_value=[
            {"SECID": "RU000A", "SHORTNAME": "Test", "ISSUEDATE": date.today().isoformat()},
        ])
        mock_moex_collector.return_value = mock_moex_instance

        mock_db.execute = AsyncMock()
        mock_db.add = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        mock_collector_instance = AsyncMock()
        mock_collector_instance.fetch_by_ticker = AsyncMock(return_value={
            "isin": "RU000A12345",
            "offering_date": None,
        })
        mock_bond_collector.return_value = mock_collector_instance

        with patch("src.analysis.bonds.new_bond_locator.find_new_bonds") as mock_find:
            mock_find.return_value = []
            with patch("src.db.connection.get_session") as mock_get_session:
                mock_get_session.return_value.__enter__.return_value = MagicMock()
                result = await discover_new_bonds(mock_db)
                mock_db.rollback.assert_called()
                assert result == []

    @patch("src.collectors.moex.MOEXCollector")
    @patch("src.collectors.bonds.BondOfferingCollector")
    async def test_skips_bonds_older_than_max_age(
        self, mock_bond_collector, mock_moex_collector, mock_db
    ):
        mock_moex_instance = AsyncMock()
        old_date = (date.today() - timedelta(days=200)).isoformat()
        mock_moex_instance.get_bonds = AsyncMock(return_value=[
            {"SECID": "RU000A", "SHORTNAME": "Old Bond", "ISSUEDATE": old_date},
        ])
        mock_moex_collector.return_value = mock_moex_instance

        with patch("src.analysis.bonds.new_bond_locator.find_new_bonds") as mock_find:
            mock_find.return_value = [{"ticker": "RU000A"}]
            with patch("src.db.connection.get_session") as mock_get_session:
                mock_get_session.return_value.__enter__.return_value = MagicMock()
                result = await discover_new_bonds(mock_db)
                assert result == [{"ticker": "RU000A"}]
