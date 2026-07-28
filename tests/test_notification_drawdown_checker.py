from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.notifications.drawdown_checker import DrawdownAlert, check_drawdown, format_drawdown_alert


def make_alert(**kw) -> DrawdownAlert:
    defaults = dict(
        current_dd=12.5,
        reason="market drop",
        affected_positions=[{"ticker": "SBER", "change_pct": -0.15}],
        is_market_risk=False,
        recommendation="hold",
    )
    defaults.update(kw)
    return DrawdownAlert(**defaults)


class TestCheckDrawdown:
    @patch("src.notifications.drawdown_checker.get_session")
    def test_no_drawdown_returns_none(self, mock_get_session):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_get_session.return_value.__enter__.return_value = mock_db
        result = check_drawdown()
        assert result is None


class TestFormatDrawdownAlert:
    def test_alert_contains_ticker(self):
        alert = make_alert()
        text = format_drawdown_alert(alert)
        assert "SBER" in text

    def test_market_risk_label(self):
        alert = make_alert(is_market_risk=True)
        text = format_drawdown_alert(alert)
        assert "РЫНОЧНЫЙ" in text
