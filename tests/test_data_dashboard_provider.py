from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.data.dashboard_provider import DashboardDataProvider


class TestDashboardDataProvider:
    def test_init(self):
        provider = DashboardDataProvider()
        assert provider is not None

    def test_get_news_summary(self):
        provider = DashboardDataProvider()
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        result = provider.get_news_dashboard_data(mock_db)
        assert isinstance(result, dict)

    def test_get_news_summary_with_data(self):
        provider = DashboardDataProvider()
        mock_db = MagicMock()
        mock_news = MagicMock(id=1, title="test", sentiment_score=0.5, is_relevant=True)
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_news
        ]
        mock_db.query.return_value.count.return_value = 5
        result = provider.get_news_dashboard_data(mock_db)
        assert isinstance(result, dict)
        if "total_articles" in result:
            assert result["total_articles"] == 5
