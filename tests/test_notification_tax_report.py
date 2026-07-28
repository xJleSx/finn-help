from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.notifications.tax_report import TaxReport, generate_tax_report, format_tax_report


def make_report(**kw) -> TaxReport:
    defaults = dict(period="June 2026", coupon_income=5000.0, coupon_tax=650.0, capital_gain=2000.0, capital_tax=260.0, ldv_applicable=True, total_tax_due=910.0, payment_date="до 01.07.2026")
    defaults.update(kw)
    return TaxReport(**defaults)



class TestFormatTaxReport:
    def test_with_report(self):
        report = make_report()
        text = format_tax_report(report)
        assert "5000" in text
        assert "June" in text
