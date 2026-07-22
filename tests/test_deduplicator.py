from unittest.mock import MagicMock

from src.alerts.deduplicator import AlertDeduplicator, _content_hash


def _make_news(title: str, content: str = "", category: str = "news", subcategory: str = "market", source: str = "source1"):
    n = MagicMock()
    n.title = title
    n.content = content
    n.category = category
    n.subcategory = subcategory
    n.source_name = source
    return n


class TestContentHash:
    def test_same_content_same_hash(self):
        h1 = _content_hash(_make_news("Title A", "Content A"))
        h2 = _content_hash(_make_news("Title A", "Content A"))
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = _content_hash(_make_news("Title A", "Content A"))
        h2 = _content_hash(_make_news("Title B", "Content B"))
        assert h1 != h2


class TestAlertDeduplicator:
    def test_first_article_not_duplicate(self):
        dedup = AlertDeduplicator(hours=24)
        article = _make_news("Test", "Content")
        assert dedup.is_duplicate(article) is False

    def test_same_article_twice_is_duplicate(self):
        dedup = AlertDeduplicator(hours=24)
        article = _make_news("Test", "Content")
        dedup.is_duplicate(article)
        assert dedup.is_duplicate(article) is True

    def test_same_category_different_content_not_duplicate(self):
        dedup = AlertDeduplicator(hours=24)
        a1 = _make_news("Title A", "Content A")
        a2 = _make_news("Title B", "Content B")
        dedup.is_duplicate(a1)
        assert dedup.is_duplicate(a2) is False

    def test_reset_clears_state(self):
        dedup = AlertDeduplicator(hours=24)
        article = _make_news("Test", "Content")
        dedup.is_duplicate(article)
        dedup.reset()
        assert dedup.is_duplicate(article) is False

    def test_different_category_not_duplicate(self):
        dedup = AlertDeduplicator(hours=24)
        a1 = _make_news("Test", "Content", category="news")
        a2 = _make_news("Test", "Content", category="alert")
        dedup.is_duplicate(a1)
        assert dedup.is_duplicate(a2) is False
