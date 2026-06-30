from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from src.db.models import (
    BondOffering,
    CompanyProfile,
    CorporateEvent,
    FinancialReport,
    FundamentalMetric,
    Instrument,
)
from src.interfaces.response_formatter import (
    build_bond_analysis,
    build_corporate_events_block,
    build_enriched_context_block,
    build_financial_highlights,
    build_fundamental_comparison,
    build_profile_block,
    fmt_pct,
    fmt_rub,
    load_company_profile,
    load_financial_report,
    load_upcoming_events,
)


class TestHelpers:
    def test_fmt_pct_none(self):
        assert fmt_pct(None) == "\u2014"

    def test_fmt_pct_value(self):
        assert fmt_pct(12.345) == "12.3%"

    def test_fmt_rub_none(self):
        assert fmt_rub(None) == "\u2014"

    def test_fmt_rub_million(self):
        result = fmt_rub(1_500_000)
        assert "1.50" in result
        assert "млн" in result

    def test_fmt_rub_billion(self):
        result = fmt_rub(2_500_000_000)
        assert "2.50" in result
        assert "млрд" in result

    def test_fmt_rub_trillion(self):
        result = fmt_rub(5_000_000_000_000)
        assert "5.00" in result
        assert "трлн" in result


class TestBuildProfileBlock:
    def test_none(self):
        assert build_profile_block(None) == ""

    def test_with_all_fields(self):
        p = CompanyProfile(
            instrument_id=1,
            description="Крупнейший банк России.",
            website="sberbank.ru",
            industry="Финансы",
            employees=250000,
            founded_year=1841,
        )
        result = build_profile_block(p)
        assert "Крупнейший банк России." in result
        assert "Сайт:" in result
        assert "sberbank.ru" in result
        assert "Отрасль: Финансы" in result
        assert "Сотрудники:" in result
        assert "250 000" in result

    def test_minimal(self):
        p = CompanyProfile(instrument_id=1)
        assert build_profile_block(p) == ""


class TestBuildFinancialHighlights:
    def test_none(self):
        assert build_financial_highlights(None) == []

    def test_all_fields(self):
        r = FinancialReport(
            instrument_id=1,
            report_date=date(2024, 12, 31),
            period_type="FY",
            net_profit=500_000_000_000,
            revenue=1_500_000_000_000,
            roe=15.0,
            roa=2.5,
            net_margin=8.0,
            npl_ratio=2.0,
            capital_adequacy=12.0,
            total_assets=10_000_000_000_000,
            total_equity=500_000_000_000,
        )
        h = build_financial_highlights(r)
        assert len(h) >= 8
        assert any("Чистая прибыль" in x and "млрд" in x for x in h)
        assert any("ROE (2024-12-31): 15.0%" in x for x in h)
        assert any("NPL (2024-12-31): 2.0%" in x for x in h)
        assert any("Активы" in x and "трлн" in x for x in h)

    def test_bank_specific(self):
        r = FinancialReport(
            instrument_id=1,
            report_date=date(2024, 12, 31),
            period_type="FY",
            net_interest_income=200_000_000_000,
            operating_income=300_000_000_000,
        )
        h = build_financial_highlights(r)
        assert any("Чистые процентные доходы" in x for x in h)
        assert any("Операционные доходы" in x for x in h)


class TestBuildBondAnalysis:
    def test_none(self):
        assert build_bond_analysis(None) == []

    def test_full(self):
        o = BondOffering(
            instrument_id=1,
            coupon_type="fixed",
            coupon_rate=8.5,
            yield_to_maturity=7.2,
            credit_rating="AAA",
            maturity_date=date(2028, 6, 15),
            coupon_period_days=182,
            volume=5_000_000_000,
            has_amortization=False,
            has_offer=True,
            min_lot_rub=1000,
            qual_investor_only=False,
        )
        b = build_bond_analysis(o)
        assert any("фиксированный" in x for x in b)
        assert any("8.5%" in x for x in b)
        assert any("YTM: 7.2%" in x for x in b)
        assert any("AAA" in x for x in b)
        assert any("15.06.2028" in x for x in b)
        assert any("Оферта: да" in x for x in b)

    def test_floater(self):
        o = BondOffering(instrument_id=1, coupon_type="float", coupon_rate=9.0)
        b = build_bond_analysis(o)
        assert any("флоатер" in x for x in b)


class TestBuildCorporateEventsBlock:
    def test_empty(self):
        assert build_corporate_events_block([]) == []

    def test_various_types(self):
        events = [
            CorporateEvent(
                instrument_id=1,
                event_type="dividend",
                announcement_date=date(2025, 7, 15),
                dividend_amount=50.0,
                status="approved",
            ),
            CorporateEvent(
                instrument_id=1,
                event_type="buyback",
                announcement_date=date(2025, 8, 1),
            ),
            CorporateEvent(
                instrument_id=1,
                event_type="split",
                announcement_date=date(2025, 9, 1),
            ),
        ]
        b = build_corporate_events_block(events)
        assert len(b) == 3
        assert any("Dividend" in x for x in b)
        assert any("50" in x for x in b)
        assert any("Buyback" in x for x in b)
        assert any("Split" in x for x in b)

    def test_truncated(self):
        events = [CorporateEvent(instrument_id=1, event_type="dividend") for _ in range(10)]
        assert len(build_corporate_events_block(events, max_items=3)) == 3


class TestBuildFundamentalComparison:
    def test_none(self):
        assert build_fundamental_comparison(None) == []

    def test_with_data(self):
        fm = FundamentalMetric(
            instrument_id=1,
            market_cap=500_000_000_000,
            pe_ratio=8.5,
            pb_ratio=1.2,
            eps=120.0,
            roe=14.0,
            revenue=600_000_000_000,
            net_income=60_000_000_000,
        )
        b = build_fundamental_comparison(fm)
        assert any("Капитализация" in x for x in b)
        assert any("P/E: 8.5" in x for x in b)
        assert any("P/B: 1.2" in x for x in b)
        assert any("ROE: 14.0%" in x for x in b)

    def test_with_sector_avg(self):
        fm = FundamentalMetric(instrument_id=1, pe_ratio=8.5, pb_ratio=1.2)
        avg = {"pe_ratio": 10.0, "pb_ratio": 1.5}
        b = build_fundamental_comparison(fm, sector_avg=avg)
        assert any("-15%" in x for x in b)
        assert any("-20%" in x for x in b)


class TestLoadFunctions:
    def test_load_company_profile(self):
        db = MagicMock()
        q = MagicMock()
        db.query.return_value = q
        q.filter.return_value.first.return_value = "cached"
        assert load_company_profile(db, 1) == "cached"

    def test_load_financial_report(self):
        db = MagicMock()
        q = MagicMock()
        db.query.return_value = q
        q.filter.return_value.order_by.return_value.first.return_value = "cached"
        assert load_financial_report(db, 1) == "cached"

    def test_load_upcoming_events(self):
        db = MagicMock()
        q = MagicMock()
        db.query.return_value = q
        q.filter.return_value.order_by.return_value.all.return_value = []
        assert load_upcoming_events(db, 1) == []


class TestBuildEnrichedContextBlock:
    def test_empty_instrument(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        inst = MagicMock(spec=Instrument)
        inst.id = 1
        inst.instrument_type = "stock"

        result = build_enriched_context_block(db, inst)
        assert result == ""

    def test_stock_with_all_data(self):
        profile = CompanyProfile(
            instrument_id=1,
            description="Крупнейшая компания.",
            industry="IT",
        )
        report = FinancialReport(
            instrument_id=1,
            report_date=date(2024, 12, 31),
            net_profit=100_000_000_000,
        )

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            if model == CompanyProfile:
                q.filter.return_value.first.return_value = profile
                q.filter.return_value.order_by.return_value.first.return_value = None
                q.filter.return_value.order_by.return_value.all.return_value = []
            elif model == FinancialReport:
                q.filter.return_value.order_by.return_value.first.return_value = report
            else:
                q.filter.return_value.first.return_value = None
                q.filter.return_value.order_by.return_value.first.return_value = None
                q.filter.return_value.order_by.return_value.all.return_value = []
            return q

        db.query.side_effect = _query

        inst = MagicMock(spec=Instrument)
        inst.id = 1
        inst.instrument_type = "stock"

        result = build_enriched_context_block(db, inst)
        assert "Профиль компании" in result
        assert "Крупнейшая компания." in result
        assert "Финансовая отчётность" in result
        assert "Чистая прибыль" in result

    def test_bond_adds_offering(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [None, None, None]
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        inst = MagicMock(spec=Instrument)
        inst.id = 1
        inst.instrument_type = "bond"

        result = build_enriched_context_block(db, inst)
        assert result == ""
