from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analysis.ml.news_impact import NewsImpactModel
from src.analysis.ml.news_impact_features import (
    ALL_FEATURE_COLS,
    SUBCATEGORY_VALUES,
    build_training_data,
    extract_features,
    forward_return,
)
from src.config import settings
from src.db.models import Base, Instrument, News, NewsInstrument, Price


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def instrument(db_session):
    inst = Instrument(id=1, ticker="SBER", full_name="Sberbank", sector="Финансы", instrument_type="stock")
    db_session.add(inst)
    db_session.commit()
    return inst


@pytest.fixture
def prices(db_session, instrument):
    rows = []
    base = datetime.now(timezone.utc).date()
    for i in range(60):
        rows.append(
            Price(
                instrument_id=instrument.id,
                date=base - timedelta(days=59 - i),
                close=100.0 + i * 0.5 + np.random.randn() * 2,
                volume=1000000 + int(np.random.randn() * 100000),
            )
        )
    db_session.add_all(rows)
    db_session.commit()
    return rows


@pytest.fixture
def news_articles(db_session, instrument):
    now = datetime.now(timezone.utc)
    for i in range(20):
        article = News(
            id=i + 1,
            url=f"http://test.ru/{i}",
            title=f"Test news {i}",
            summary=f"Summary {i}",
            source_type="rss",
            source_name="Интерфакс",
            published_at=now - timedelta(days=i * 2),
            sentiment_score=0.5 if i % 2 == 0 else -0.3,
            sentiment_weighted=0.4 if i % 2 == 0 else -0.2,
            sentiment="positive" if i % 2 == 0 else "negative",
            impact_score=5.0 + i * 0.5,
            source_weight=1.0,
            source_count=2,
            is_relevant=True,
            category="MACRO" if i < 10 else "SECTOR",
            subcategory="monetary_policy" if i < 5 else ("energy" if i < 10 else "earnings"),
        )
        db_session.add(article)
        db_session.flush()
        db_session.add(NewsInstrument(news_id=article.id, instrument_id=instrument.id))
    db_session.commit()
    return db_session.query(News).order_by(News.id).all()


class TestExtractFeatures:
    def test_extract_basic(self, db_session, news_articles):
        feat = extract_features(db_session, news_articles[0])
        assert isinstance(feat, dict)
        assert feat["sentiment_score"] == 0.5
        assert feat["impact_score"] == 5.0
        assert feat["source_weight"] == 1.0
        assert feat["source_count"] == 2
        assert feat["sentiment_positive"] == 1.0
        assert feat["sentiment_negative"] == 0.0

    def test_extract_category_onehot(self, db_session, news_articles):
        feat = extract_features(db_session, news_articles[0])
        assert feat["cat_MACRO"] == 1.0
        assert feat["cat_SECTOR"] == 0.0

    def test_extract_subcategory_onehot(self, db_session, news_articles):
        feat = extract_features(db_session, news_articles[0])
        assert feat["subcat_monetary_policy"] == 1.0

    def test_extract_unknown_subcategory(self, db_session, instrument):
        article = News(
            id=100, title="Test", summary="", source_type="rss",
            published_at=datetime.now(timezone.utc),
            sentiment="neutral", is_relevant=True,
            category="COMPANY", subcategory="unknown_sub",
        )
        db_session.add(article)
        db_session.flush()
        db_session.add(NewsInstrument(news_id=article.id, instrument_id=instrument.id))
        db_session.commit()

        feat = extract_features(db_session, article)
        for s in SUBCATEGORY_VALUES:
            assert feat[f"subcat_{s}"] == 0.0

    def test_time_features(self, db_session, news_articles):
        feat = extract_features(db_session, news_articles[0])
        assert "hour_of_day" in feat
        assert "day_of_week" in feat
        assert 0 <= feat["hour_of_day"] <= 23
        assert 0 <= feat["day_of_week"] <= 6

    def test_all_feature_cols_present(self, db_session, news_articles):
        feat = extract_features(db_session, news_articles[0])
        for col in ALL_FEATURE_COLS:
            assert col in feat, f"Missing feature: {col}"

    def test_market_features_when_linked(self, db_session, instrument, prices, news_articles):
        feat = extract_features(db_session, news_articles[0])
        assert "volatility_20d" in feat
        assert feat["volatility_20d"] > 0

    def test_no_linked_instrument(self, db_session):
        article = News(
            id=200, title="orphan", summary="", source_type="rss",
            published_at=datetime.now(timezone.utc),
            sentiment="neutral", is_relevant=True,
            category="MACRO",
        )
        db_session.add(article)
        db_session.commit()
        feat = extract_features(db_session, article)
        for c in ["return_5d_before", "volatility_20d", "volume_change_5d"]:
            assert c in feat
            assert feat[c] == 0.0


class TestForwardReturn:
    def test_forward_return_positive(self, db_session, instrument, prices):
        after = datetime.now(timezone.utc) - timedelta(days=30)
        ret = forward_return(db_session, instrument.id, after, days=1)
        assert isinstance(ret, float)

    def test_forward_return_zero_no_data(self, db_session):
        ret = forward_return(db_session, 999, datetime.now(timezone.utc), days=1)
        assert ret == 0.0


class TestBuildTrainingData:
    def test_build_training_data(self, db_session, instrument, prices, news_articles):
        df = build_training_data(db_session, "SBER", max_articles=10, days_back=365)
        assert not df.empty
        assert "return_1d" in df.columns
        assert "return_3d" in df.columns
        assert "return_5d" in df.columns

    def test_build_training_data_unknown_ticker(self, db_session):
        df = build_training_data(db_session, "NONEXISTENT")
        assert df.empty

    def test_build_training_data_no_news(self, db_session, instrument):
        df = build_training_data(db_session, "SBER", max_articles=0)
        assert df.empty


class TestNewsImpactModel:
    def test_init(self):
        model = NewsImpactModel("SBER")
        assert model._ticker == "SBER"
        assert model._models == {}

    def test_horizons_from_config(self):
        model = NewsImpactModel()
        h = model.horizons
        assert all(isinstance(x, int) for x in h)
        assert len(h) >= 3

    def test_model_name(self):
        model = NewsImpactModel("SBER")
        name = model._model_name(1)
        assert "news_impact" in name
        assert "SBER" in name
        assert "1d" in name

    def test_create_model(self):
        model = NewsImpactModel()
        m = model._create_model()
        assert m is not None
        assert hasattr(m, "fit")

    def test_feature_importance_empty_when_no_model(self):
        model = NewsImpactModel()
        assert model._feature_importance(None) == []

    def test_predict_no_model(self, db_session):
        model = NewsImpactModel("UNIQUE_TICKER_NO_COLLISION_12345")
        article = News(
            id=9999, title="Test", summary="", source_type="rss",
            published_at=datetime.now(timezone.utc),
            sentiment="neutral", is_relevant=True, category="MACRO",
        )
        db_session.add(article)
        db_session.commit()
        result = model.predict(db_session, article, horizon_days=1)
        assert result["predicted_return"] == 0.0
        assert not result["model_loaded"]

    def test_train_and_predict(self, db_session, instrument, prices, news_articles, monkeypatch):
        monkeypatch.setattr(settings, "ml_impact_min_train_samples", 10)
        model = NewsImpactModel("SBER")
        result = model.train(db_session)
        assert result["trained"]
        assert "horizons" in result

        pred = model.predict(db_session, news_articles[0], horizon_days=1)
        assert isinstance(pred["predicted_return"], float)
        assert 0 <= pred["confidence"] <= 1.0
        assert pred["model_loaded"]

    def test_train_not_enough_samples(self, db_session):
        model = NewsImpactModel("EMPTY")
        result = model.train(db_session)
        assert not result["trained"]

    def test_evaluate(self, db_session, instrument, prices, news_articles, monkeypatch):
        monkeypatch.setattr(settings, "ml_impact_min_train_samples", 10)
        model = NewsImpactModel("SBER")
        model.train(db_session)
        ev = model.evaluate(db_session)
        assert isinstance(ev, dict)
        for h in model.horizons:
            key = f"{h}d"
            if key in ev:
                assert "rmse" in ev[key]
                assert "mae" in ev[key]
                assert "direction_accuracy" in ev[key]

    def test_feature_importance_after_train(self, db_session, instrument, prices, news_articles, monkeypatch):
        monkeypatch.setattr(settings, "ml_impact_min_train_samples", 10)
        model = NewsImpactModel("SBER")
        model.train(db_session)
        for h in model.horizons:
            if h in model._models:
                fi = model._feature_importance(model._models[h])
                assert isinstance(fi, list)
                if fi:
                    assert "feature" in fi[0]
                    assert "importance" in fi[0]

    def test_predict_all_horizons(self, db_session, instrument, prices, news_articles, monkeypatch):
        monkeypatch.setattr(settings, "ml_impact_min_train_samples", 10)
        model = NewsImpactModel("SBER")
        model.train(db_session)
        for h in model.horizons:
            pred = model.predict(db_session, news_articles[0], horizon_days=h)
            assert isinstance(pred["predicted_return"], float)
