from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.notifications.calendar_checker import CalendarEvent, format_coupon_alert, format_redemption_alert, get_upcoming_events


def make_event(**kw):
    defaults = dict(event_type="coupon", ticker="SU26238RMFS5", name="ОФЗ 26238", event_date=date.today(), amount_per_unit=42.5, quantity=10, total_amount=425.0, days_until=3)
    defaults.update(kw)
    return CalendarEvent(**defaults)


class TestGetUpcomingEvents:
    @patch("src.notifications.calendar_checker.get_session")
    def test_empty_db_returns_empty(self, mock_get_session):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_session.return_value.__enter__.return_value = mock_db
        result = get_upcoming_events(14)
        assert len(result.coupons) == 0
        assert len(result.redemptions) == 0


class TestFormatCouponAlert:
    def test_3_days(self):
        ev = make_event(days_until=3)
        text = format_coupon_alert(ev, 3)
        assert "SU26238RMFS5" in text

    def test_0_days(self):
        ev = make_event(days_until=0)
        text = format_coupon_alert(ev, 0)
        assert "сегодня" in text.lower()


class TestFormatRedemptionAlert:
    def test_7_days(self):
        ev = make_event(event_type="redemption", days_until=7)
        text = format_redemption_alert(ev, 7)
        assert "SU26238RMFS5" in text

    def test_today(self):
        ev = make_event(event_type="redemption", days_until=0)
        text = format_redemption_alert(ev, 0)
        assert "СЕГОДНЯ" in text
