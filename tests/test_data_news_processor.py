from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.data.news_processor import NewsDeduplicator


class TestNewsDeduplicator:
    def test_init_default_embedding(self):
        dedup = NewsDeduplicator()
        assert dedup.SIMILARITY_THRESHOLD == 0.85

    def test_init_custom_embedding_fn(self):
        fn = lambda x: [0.5, 0.5]
        dedup = NewsDeduplicator(embedding_fn=fn)
        result = dedup.embed_article("test", "content")
        assert result == [0.5, 0.5]

    def test_embed_article_no_summary(self):
        dedup = NewsDeduplicator(embedding_fn=lambda x: [1.0])
        result = dedup.embed_article("title only", "")
        assert result == [1.0]

    def test_find_duplicates_empty(self):
        dedup = NewsDeduplicator()
        assert dedup.find_duplicates([], None) == []

    def test_find_duplicates_single(self):
        dedup = NewsDeduplicator()
        articles = [{"id": 1, "title": "test", "summary": "content"}]
        assert dedup.find_duplicates(articles, None) == []

    def test_find_duplicates_two_similar(self):
        dedup = NewsDeduplicator()
        with patch.object(dedup, "embed_article") as mock_embed:
            mock_embed.side_effect = [
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
            ]
            articles = [
                {"id": 1, "title": "a", "summary": "b"},
                {"id": 2, "title": "c", "summary": "d"},
            ]
            result = dedup.find_duplicates(articles, None)
            assert (1, 2) in result or (2, 1) in result

    def test_embed_article_fallback(self):
        dedup = NewsDeduplicator()
        result = dedup.embed_article("test title", "test summary")
        assert len(result) == 768

    def test_find_duplicates_embedding_failure(self):
        dedup = NewsDeduplicator()
        with patch.object(dedup, "embed_article", side_effect=Exception("fail")):
            articles = [{"id": 1, "title": "a", "summary": "b"}]
            assert dedup.find_duplicates(articles, None) == []

    def test_cluster_articles_into_events_empty(self):
        dedup = NewsDeduplicator()
        assert dedup.cluster_articles_into_events([], None) == {}

    def test_cluster_articles_into_events_single(self):
        dedup = NewsDeduplicator()
        article = MagicMock(id=1, title="test", summary="content")
        assert dedup.cluster_articles_into_events([article], None) == {}
