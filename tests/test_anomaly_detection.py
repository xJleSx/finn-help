from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.analysis.anomaly.autoencoder import AutoencoderAnomalyDetector
from src.analysis.anomaly.detector import AnomalyDetector
from src.analysis.anomaly.features import (
    article_counts_per_day,
    build_anomaly_feature_vector,
    rolling_volume_features,
    sentiment_features_per_day,
    source_frequencies,
    topic_frequencies,
)
from src.analysis.anomaly.sentiment_anomaly import SentimentAnomalyDetector
from src.analysis.anomaly.source_anomaly import SourceAnomalyDetector
from src.analysis.anomaly.topic_anomaly import TopicAnomalyDetector
from src.analysis.anomaly.volume_anomaly import VolumeAnomalyDetector
from src.db.models import Base, Instrument, News, NewsInstrument, Price


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def instrument(db_session: Session) -> Instrument:
    inst = Instrument(id=1, ticker="TEST", full_name="Test Corp")
    db_session.add(inst)
    db_session.commit()
    return inst


@pytest.fixture
def news_articles(db_session: Session, instrument: Instrument) -> list[News]:
    now = datetime.now(timezone.utc)
    articles = []
    for i in range(30):
        day = now - timedelta(days=29 - i)
        article = News(
            id=i + 1,
            title=f"Article {i}",
            summary="",
            source_type="rss",
            source_name="SourceA" if i % 3 == 0 else ("SourceB" if i % 3 == 1 else "SourceC"),
            published_at=day,
            sentiment="positive" if i % 2 == 0 else "negative",
            sentiment_score=0.5 if i % 2 == 0 else -0.3,
            category="MACRO" if i % 2 == 0 else "COMPANY",
            subcategory="monetary_policy" if i % 2 == 0 else "earnings",
            is_relevant=True,
            impact_score=0.1 * (i % 5),
            source_weight=0.5,
            source_count=1,
        )
        db_session.add(article)
        db_session.flush()
        link = NewsInstrument(news_id=article.id, instrument_id=instrument.id)
        db_session.add(link)
        articles.append(article)
    db_session.commit()
    return articles


@pytest.fixture
def prices(db_session: Session, instrument: Instrument) -> list[Price]:
    today = datetime.now(timezone.utc).date()
    prices_list = []
    for i in range(60):
        day = today - timedelta(days=59 - i)
        price = Price(
            instrument_id=instrument.id,
            date=day,
            open=100.0 + i * 0.5,
            high=101.0 + i * 0.5,
            low=99.0 + i * 0.5,
            close=100.5 + i * 0.5,
            volume=1000 + i * 10,
        )
        db_session.add(price)
        prices_list.append(price)
    db_session.commit()
    return prices_list


# --- Test Feature Functions ---

class TestArticleCountsPerDay:
    def test_returns_dataframe(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        df = article_counts_per_day(db_session, "TEST")
        assert not df.empty
        assert "count" in df.columns

    def test_unknown_ticker(self, db_session: Session):
        df = article_counts_per_day(db_session, "UNKNOWN")
        assert df.empty

    def test_respects_days_back(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        df = article_counts_per_day(db_session, "TEST", days_back=5)
        assert len(df) <= 6


class TestRollingVolumeFeatures:
    def test_returns_features(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        df = rolling_volume_features(db_session, "TEST")
        assert not df.empty
        assert "vol_ma_7d" in df.columns
        assert "vol_zscore_7d" in df.columns

    def test_insufficient_data(self, db_session: Session):
        df = rolling_volume_features(db_session, "UNKNOWN")
        assert df.empty


class TestSentimentFeaturesPerDay:
    def test_returns_features(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        df = sentiment_features_per_day(db_session, "TEST")
        assert not df.empty
        assert "sent_ma_7d" in df.columns
        assert "sent_change_1d" in df.columns


class TestSourceFrequencies:
    def test_returns_dict(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        freqs = source_frequencies(db_session)
        assert isinstance(freqs, dict)
        assert len(freqs) > 0

    def test_filter_by_category(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        freqs = source_frequencies(db_session, category="MACRO")
        assert isinstance(freqs, dict)


class TestTopicFrequencies:
    def test_returns_dict(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        freqs = topic_frequencies(db_session)
        assert isinstance(freqs, dict)
        assert "TEST" in freqs

    def test_topic_keys(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        freqs = topic_frequencies(db_session)
        for topic_tuple in freqs.get("TEST", {}):
            assert isinstance(topic_tuple, tuple)
            assert len(topic_tuple) == 2


class TestBuildAnomalyFeatureVector:
    def test_returns_array(
        self, db_session: Session, instrument: Instrument,
        news_articles: list[News], prices: list[Price],
    ):
        vec = build_anomaly_feature_vector(db_session, news_articles[0])
        assert isinstance(vec, np.ndarray)
        assert vec.ndim == 1
        assert vec.dtype == np.float32


# --- Test Detectors ---

class TestVolumeAnomalyDetector:
    def test_init(self):
        d = VolumeAnomalyDetector("TEST")
        assert d.ticker == "TEST"
        assert not d.trained

    def test_train_no_ticker(self, db_session: Session):
        d = VolumeAnomalyDetector()
        result = d.train(db_session)
        assert not result["trained"]

    def test_train_insufficient_data(self, db_session: Session):
        d = VolumeAnomalyDetector("UNKNOWN")
        result = d.train(db_session)
        assert not result["trained"]

    def test_train_and_predict(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        d = VolumeAnomalyDetector("TEST")
        result = d.train(db_session)
        assert result["trained"]
        score = d.predict_article(db_session, news_articles[0])
        assert 0.0 <= score <= 1.0

    def test_predict_no_model(self, db_session: Session, news_articles: list[News]):
        d = VolumeAnomalyDetector("TEST")
        score = d.predict_article(db_session, news_articles[0])
        assert score == 0.0


class TestSentimentAnomalyDetector:
    def test_init(self):
        d = SentimentAnomalyDetector("TEST")
        assert d.ticker == "TEST"

    def test_train_no_ticker(self, db_session: Session):
        d = SentimentAnomalyDetector()
        result = d.train(db_session)
        assert not result["trained"]

    def test_train_and_predict(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        d = SentimentAnomalyDetector("TEST")
        result = d.train(db_session)
        assert result["trained"]
        score = d.predict_article(db_session, news_articles[0])
        assert 0.0 <= score <= 1.0


class TestSourceAnomalyDetector:
    def test_predict_no_train(self, db_session: Session, news_articles: list[News]):
        d = SourceAnomalyDetector()
        score = d.predict_article(news_articles[0])
        assert score == 0.0

    def test_train_and_predict(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        d = SourceAnomalyDetector()
        result = d.train(db_session)
        assert result["trained"]
        score = d.predict_article(news_articles[0])
        assert 0.0 <= score <= 1.0

    def test_predict_unknown_source(self, db_session: Session, news_articles: list[News]):
        d = SourceAnomalyDetector()
        d.train(db_session)
        article = News(
            id=999, title="Test", summary="", source_type="rss",
            source_name="UnknownSourceXYZ", published_at=datetime.now(timezone.utc),
            category="MACRO",
        )
        score = d.predict_article(article)
        assert score == 0.0


class TestTopicAnomalyDetector:
    def test_predict_no_train(self, db_session: Session, news_articles: list[News]):
        d = TopicAnomalyDetector()
        score = d.predict_article(news_articles[0])
        assert score == 0.0

    def test_train_and_predict(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        d = TopicAnomalyDetector()
        result = d.train(db_session)
        assert result["trained"]
        score = d.predict_article(news_articles[0])
        assert 0.0 <= score <= 1.0

    def test_predict_unknown_topic(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        d = TopicAnomalyDetector()
        d.train(db_session)
        article = News(
            id=999, title="Test", summary="", source_type="rss",
            published_at=datetime.now(timezone.utc),
            category="SECTOR", subcategory="energy",
        )
        score = d.predict_article(article)
        assert 0.0 <= score <= 1.0

    def test_predict_unknown_ticker(self, db_session: Session):
        d = TopicAnomalyDetector()
        d._trained = True
        article = News(
            id=1, title="Test", summary="", source_type="rss",
            published_at=datetime.now(timezone.utc),
            category="MACRO",
        )
        score = d.predict_article(article)
        assert score == 0.0


class TestAutoencoderAnomalyDetector:
    def test_init(self):
        d = AutoencoderAnomalyDetector(input_dim=10)
        assert not d.trained

    def test_predict_no_model(self, db_session: Session, news_articles: list[News], prices: list[Price]):
        d = AutoencoderAnomalyDetector(input_dim=24)
        vec = build_anomaly_feature_vector(db_session, news_articles[0])
        score = d.predict(vec)
        assert score == 0.0

    def test_predict_article_no_model(self, db_session: Session, news_articles: list[News], prices: list[Price]):
        d = AutoencoderAnomalyDetector(input_dim=24)
        score = d.predict_article(db_session, news_articles[0])
        assert score == 0.0

    def test_train_insufficient_data(self, db_session: Session):
        d = AutoencoderAnomalyDetector(input_dim=24)
        result = d.train(db_session)
        assert not result["trained"]

    def test_train_and_predict(
        self, db_session: Session, instrument: Instrument,
        news_articles: list[News], prices: list[Price],
    ):
        d = AutoencoderAnomalyDetector(input_dim=24)
        result = d.train(db_session, "TEST")
        assert result["trained"]
        vec = build_anomaly_feature_vector(db_session, news_articles[0])
        score = d.predict(vec)
        assert 0.0 <= score <= 1.0

    def test_predict_pads_features(
        self, db_session: Session, news_articles: list[News], prices: list[Price],
    ):
        d = AutoencoderAnomalyDetector(input_dim=50)
        score = d.predict_article(db_session, news_articles[0])
        assert score == 0.0


class TestAnomalyDetector:
    def test_init(self):
        d = AnomalyDetector("TEST")
        assert d.ticker == "TEST"
        assert d.volume is not None
        assert d.sentiment is not None

    def test_predict_article_no_train(self, db_session: Session, instrument: Instrument, news_articles: list[News]):
        d = AnomalyDetector("TEST")
        result = d.predict_article(db_session, news_articles[0])
        assert "anomaly_score" in result
        assert "is_anomaly" in result
        assert "details" in result
        assert result["anomaly_score"] == 0.0
        assert not result["is_anomaly"]

    def test_train_and_predict(
        self, db_session: Session, instrument: Instrument,
        news_articles: list[News], prices: list[Price],
    ):
        d = AnomalyDetector("TEST")
        train_results = d.train_all(db_session)
        assert "volume" in train_results
        assert "sentiment" in train_results
        assert "source" in train_results
        assert "topic" in train_results
        assert "autoencoder" in train_results
        result = d.predict_article(db_session, news_articles[0])
        assert 0.0 <= result["anomaly_score"] <= 1.0
        assert isinstance(result["is_anomaly"], bool)

    def test_predict_multiple_articles(
        self, db_session: Session, instrument: Instrument,
        news_articles: list[News], prices: list[Price],
    ):
        d = AnomalyDetector("TEST")
        d.train_all(db_session)
        for article in news_articles[:5]:
            result = d.predict_article(db_session, article)
            assert 0.0 <= result["anomaly_score"] <= 1.0
