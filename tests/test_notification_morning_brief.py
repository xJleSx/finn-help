from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.notifications.morning_brief import build_morning_brief


class TestBuildMorningBrief:
    @patch("src.notifications.morning_brief.date")
    @patch("src.notifications.morning_brief.get_session")
    def test_returns_string(self, mock_get_session, mock_date):
        mock_date.today.return_value = date(2026, 7, 29)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_session.return_value.__enter__.return_value = mock_db
        result = build_morning_brief()
        assert isinstance(result, str)
        assert len(result) > 0


