from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestNewsCollector:
    @pytest.mark.asyncio
    async def test_fetch_all_handles_exceptions(self):
        from src.collectors.news import NewsCollector

        collector = NewsCollector()
        collector.feeds = [{"url": "http://bad.url", "name": "BadFeed"}]

        with patch.object(collector, "_fetch_feed_async", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = [{"title": "News Item"}]

            results = await collector.fetch_all(max_per_feed=1)
            assert len(results) == 1
            assert results[0]["title"] == "News Item"

    @pytest.mark.asyncio
    async def test_fetch_feed_parses_entry(self):
        from src.collectors.news import NewsCollector

        collector = NewsCollector()

        entry = MagicMock()
        entry.title = "Test Title"
        entry.link = "http://test.link"
        entry.published_parsed = None
        entry.summary = "Test summary"
        entry.get.side_effect = lambda k, d=None: {"title": entry.title, "link": entry.link}.get(k, d)

        class FakeFeed:
            entries = [entry]

        with patch("feedparser.parse", return_value=FakeFeed()):
            with patch("src.collectors.news.analyze_sentiment", return_value={"score": 0.0, "weighted_score": 0.0}):
                items = collector._fetch_feed("http://feed.url", "TestSource", 5)
                assert len(items) == 1
                assert items[0]["title"] == "Test Title"
                assert items[0]["source_name"] == "TestSource"

    @pytest.mark.asyncio
    async def test_fetch_feed_with_description(self):
        from src.collectors.news import NewsCollector

        collector = NewsCollector()

        entry = MagicMock()
        entry.title = "No Summary"
        entry.link = "http://test.link"
        entry.published_parsed = None
        del entry.summary
        entry.description = "Description fallback"
        entry.get.side_effect = lambda k, d=None: {"title": entry.title, "link": entry.link}.get(k, d)

        class FakeFeed:
            entries = [entry]

        with patch("feedparser.parse", return_value=FakeFeed()):
            with patch("src.collectors.news.analyze_sentiment", return_value={"score": 0.0, "weighted_score": 0.0}):
                items = collector._fetch_feed("http://feed.url", "TestSource", 5)
                assert len(items) == 1
                assert items[0]["source_name"] == "TestSource"

    @pytest.mark.asyncio
    async def test_fetch_all_exception_from_feed(self):
        from src.collectors.news import NewsCollector

        collector = NewsCollector()
        collector.feeds = [{"url": "http://fail.url", "name": "FailFeed"}]

        with patch.object(collector, "_fetch_feed_async", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("Connection error")

            results = await collector.fetch_all(max_per_feed=1)
            assert results == []

    @pytest.mark.asyncio
    async def test_fetch_feed_with_published_date(self):
        from src.collectors.news import NewsCollector

        collector = NewsCollector()

        class FakeTimeTuple:
            tm_year = 2024
            tm_mon = 1
            tm_mday = 15
            tm_hour = 10
            tm_min = 30
            tm_sec = 0

        entry = MagicMock()
        entry.title = "Dated News"
        entry.link = "http://test.link"
        entry.published_parsed = FakeTimeTuple()
        del entry.summary
        entry.description = "Desc"
        entry.get.side_effect = lambda k, d=None: {"title": entry.title, "link": entry.link}.get(k, d)

        class FakeFeed:
            entries = [entry]

        with patch("feedparser.parse", return_value=FakeFeed()):
            with patch("src.collectors.news.analyze_sentiment", return_value={"score": 0.0, "weighted_score": 0.0}):
                items = collector._fetch_feed("http://feed.url", "TestSource", 5)
                assert len(items) == 1
                assert items[0]["published_at"] is not None
