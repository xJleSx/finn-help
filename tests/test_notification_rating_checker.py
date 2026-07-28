from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.notifications.rating_checker import RatingChange, check_rating_changes, format_rating_alert


class TestCheckRatingChanges:
    @patch("src.notifications.rating_checker.get_session")
    def test_no_data_returns_empty(self, mock_get_session):
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = []
        mock_get_session.return_value.__enter__.return_value = mock_db
        result = check_rating_changes()
        assert result == []


class TestFormatRatingAlert:
    def make_change(self, **kw) -> RatingChange:
        defaults = dict(ticker="SU26238RMFS5", name="ОФЗ 26238", old_rating="AA+", new_rating="AA", is_downgrade=True, position_value=100000.0, portfolio_pct=15.0)
        defaults.update(kw)
        return RatingChange(**defaults)

    def test_downgrade(self):
        c = self.make_change()
        text = format_rating_alert(c)
        assert "ПОНИЖЕНИЕ" in text
        assert "AA+" in text

    def test_upgrade(self):
        c = self.make_change(is_downgrade=False, old_rating="AA", new_rating="AA+")
        text = format_rating_alert(c)
        assert "ПОВЫШЕНИЕ" in text
