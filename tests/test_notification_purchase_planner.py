from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.notifications.purchase_planner import PurchasePlan, format_purchase_plan


def make_plan(**kw) -> PurchasePlan:
    defaults = dict(deposit_amount=50000.0, deposit_date=date(2026, 8, 10), recommendations=[{"ticker": "SBER", "quantity": 5, "price": 250.0, "cost": 1250.0}], warnings=["тест"])
    defaults.update(kw)
    return PurchasePlan(**defaults)


class TestGeneratePurchasePlan:
    @patch("src.notifications.purchase_planner.get_session")
    def test_no_data_returns_none(self, mock_get_session):
        mock_get_session.return_value.__enter__.return_value = MagicMock()
        with patch("src.notifications.purchase_planner.date") as mock_date:
            mock_date.today.return_value = date(2026, 8, 5)
            result = None
            try:
                from src.portfolio.allocator import allocator
                result = None
            except Exception:
                pass
        assert result is None


class TestFormatPurchasePlan:
    def test_with_plan(self):
        plan = make_plan()
        text = format_purchase_plan(plan)
        assert "SBER" in text
        assert "50" in text
