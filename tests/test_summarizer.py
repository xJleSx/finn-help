from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.analysis.summarizer import NewsSummarizer
from src.db.models import Instrument, News, NewsInstrument


@pytest.fixture(autouse=True)
def _clean_db(db_session):
    db_session.query(NewsInstrument).delete()
    db_session.query(News).delete()
    db_session.query(Instrument).delete()
    db_session.commit()


class TestNewsSummarizerIntegration:
    def test_cluster_articles_empty(self, db_session):
        summarizer = NewsSummarizer()
        clusters = summarizer.cluster_articles(db_session, hours_back=24)
        assert clusters == []

    def test_cluster_articles_groups_by_category(self, db_session):
        inst = Instrument(ticker="SBER", full_name="Sberbank", sector="Finance")
        db_session.add(inst)
        db_session.flush()

        now = datetime.now(timezone.utc)
        news1 = News(
            title="First", category="macro", subcategory="rates",
            published_at=now, is_relevant=True, url="http://a.com/1", source_type="rss",
        )
        news2 = News(
            title="Second", category="macro", subcategory="rates",
            published_at=now, is_relevant=True, url="http://a.com/2", source_type="rss",
        )
        news3 = News(
            title="Third", category="commodity", subcategory="oil",
            published_at=now, is_relevant=True, url="http://a.com/3", source_type="rss",
        )
        db_session.add_all([news1, news2, news3])
        db_session.flush()

        db_session.add(NewsInstrument(news_id=news1.id, instrument_id=inst.id))
        db_session.add(NewsInstrument(news_id=news2.id, instrument_id=inst.id))
        db_session.commit()

        summarizer = NewsSummarizer()
        clusters = summarizer.cluster_articles(db_session, hours_back=24)

        assert len(clusters) == 2
        topics = {c.topic for c in clusters}
        assert "macro: rates" in topics
        assert "commodity: oil" in topics

    def test_fallback_summary(self, db_session):
        news = News(
            title="Test", category="macro", published_at=datetime.now(timezone.utc),
            is_relevant=True, url="http://a.com/4", source_type="rss", sentiment="positive",
        )
        db_session.add(news)
        db_session.commit()

        summarizer = NewsSummarizer()
        clusters = summarizer.cluster_articles(db_session, hours_back=24)
        assert len(clusters) == 1

        text = summarizer._fallback_summary(clusters[0])
        assert "macro" in text
        assert "positive" in text

    def test_generate_daily_digest_no_llm(self, db_session):
        news = News(
            title="Digest test", category="macro", published_at=datetime.now(timezone.utc),
            is_relevant=True, url="http://a.com/5", source_type="rss",
        )
        db_session.add(news)
        db_session.commit()

        summarizer = NewsSummarizer()
        digest = summarizer.generate_daily_digest(db_session)
        assert "Daily Digest" in digest
        assert "macro" in digest
