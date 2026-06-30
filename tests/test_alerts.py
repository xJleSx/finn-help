from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.alerts.deduplicator import AlertDeduplicator, AlertTimer
from src.alerts.engine import AlertEngine
from src.alerts.scorer import build_alert, classify_priority
from src.db.models import Base, Instrument, News, NewsInstrument, Portfolio


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def instrument(db_session: Session) -> Instrument:
    inst = Instrument(id=1, ticker="SBER", full_name="Sberbank")
    db_session.add(inst)
    db_session.commit()
    return inst


@pytest.fixture
def instrument2(db_session: Session) -> Instrument:
    inst = Instrument(id=2, ticker="GAZP", full_name="Gazprom")
    db_session.add(inst)
    db_session.commit()
    return inst


@pytest.fixture
def article_sber(db_session: Session, instrument: Instrument) -> News:
    article = News(
        id=1, title="Sber earnings beat estimates", summary="",
        source_type="rss", source_name="Interfax",
        published_at=datetime.now(timezone.utc) - timedelta(hours=2),
        sentiment="positive", sentiment_score=0.8,
        category="COMPANY", subcategory="earnings",
        is_relevant=True, impact_score=0.7, source_weight=0.5, source_count=3,
    )
    db_session.add(article)
    db_session.flush()
    db_session.add(NewsInstrument(news_id=article.id, instrument_id=instrument.id))
    db_session.commit()
    return article


@pytest.fixture
def article_gazp(db_session: Session, instrument2: Instrument) -> News:
    article = News(
        id=2, title="Gazprom sanctions risk", summary="",
        source_type="rss", source_name="RBC",
        published_at=datetime.now(timezone.utc) - timedelta(hours=6),
        sentiment="negative", sentiment_score=-0.6,
        category="GEOPOLITICAL", subcategory="sanctions",
        is_relevant=True, impact_score=0.9, source_weight=0.7, source_count=5,
    )
    db_session.add(article)
    db_session.flush()
    db_session.add(NewsInstrument(news_id=article.id, instrument_id=instrument2.id))
    db_session.commit()
    return article


@pytest.fixture
def portfolio_entry(db_session: Session, instrument: Instrument) -> Portfolio:
    entry = Portfolio(user_id=1, instrument_id=instrument.id, quantity=100, avg_price=250.0)
    db_session.add(entry)
    db_session.commit()
    return entry


# --- AlertDeduplicator ---

class TestAlertDeduplicator:
    def test_new_article_not_duplicate(self):
        dedup = AlertDeduplicator(hours=24)
        article = News(id=1, category="COMPANY", subcategory="earnings", source_name="Interfax")
        assert not dedup.is_duplicate(article)

    def test_same_article_is_duplicate(self):
        dedup = AlertDeduplicator(hours=24)
        article = News(id=1, category="COMPANY", subcategory="earnings", source_name="Interfax")
        dedup.is_duplicate(article)
        assert dedup.is_duplicate(article)

    def test_different_category_not_duplicate(self):
        dedup = AlertDeduplicator(hours=24)
        a1 = News(id=1, category="COMPANY", subcategory="earnings", source_name="Interfax")
        a2 = News(id=2, category="MACRO", subcategory="monetary_policy", source_name="Interfax")
        dedup.is_duplicate(a1)
        assert not dedup.is_duplicate(a2)

    def test_reset(self):
        dedup = AlertDeduplicator(hours=24)
        article = News(id=1, category="COMPANY", subcategory="earnings", source_name="Interfax")
        dedup.is_duplicate(article)
        dedup.reset()
        assert not dedup.is_duplicate(article)


# --- AlertTimer ---

class TestAlertTimer:
    def test_first_send_allowed(self):
        timer = AlertTimer(cooldown_minutes=60)
        assert timer.can_send("SBER")

    def test_second_send_blocked(self):
        timer = AlertTimer(cooldown_minutes=60)
        timer.can_send("SBER")
        assert not timer.can_send("SBER")

    def test_different_tickers_independent(self):
        timer = AlertTimer(cooldown_minutes=60)
        timer.can_send("SBER")
        assert timer.can_send("GAZP")

    def test_reset(self):
        timer = AlertTimer(cooldown_minutes=60)
        timer.can_send("SBER")
        timer.reset()
        assert timer.can_send("SBER")


# --- AlertEngine ---

class TestAlertEngineUnit:
    def test_classify_critical(self):
        priority, reason = classify_priority(anomaly_score=0.85, pred_return=0.01, in_portfolio=False)
        assert priority == "CRITICAL"

    def test_classify_high(self):
        priority, reason = classify_priority(anomaly_score=0.65, pred_return=0.005, in_portfolio=False)
        assert priority == "HIGH"

    def test_classify_medium(self):
        priority, reason = classify_priority(anomaly_score=0.45, pred_return=0.003, in_portfolio=False)
        assert priority == "MEDIUM"

    def test_classify_low(self):
        priority, reason = classify_priority(anomaly_score=0.1, pred_return=0.0, in_portfolio=False)
        assert priority == "LOW"

    def test_classify_portfolio_boost(self):
        priority, reason = classify_priority(anomaly_score=0.7, pred_return=0.025, in_portfolio=True)
        assert priority == "CRITICAL"

    def test_build_alert_structure(self):
        article = News(
            id=42, title="Test article", category="MACRO",
            subcategory="inflation", source_name="Interfax",
            published_at=datetime.now(timezone.utc),
        )
        anomaly = {"anomaly_score": 0.6, "is_anomaly": True, "details": {}}
        impact = {"predicted_return": 0.015, "confidence": 0.7, "model_loaded": True}
        alert = build_alert(article, "SBER", anomaly, impact, in_portfolio=True)
        assert alert["news_id"] == 42
        assert alert["ticker"] == "SBER"
        assert alert["priority"] == "HIGH"
        assert alert["in_portfolio"] is True
        assert 0.0 <= alert["priority_score"] <= 1.0

    def test_build_alert_no_impact(self):
        article = News(id=1, title="Test", published_at=datetime.now(timezone.utc))
        anomaly = {"anomaly_score": 0.0, "is_anomaly": False, "details": {}}
        impact = {"predicted_return": 0.0, "confidence": 0.0, "model_loaded": False}
        alert = build_alert(article, "SBER", anomaly, impact, in_portfolio=False)
        assert alert["priority"] == "LOW"
        # recency score = 1.0, weight = 0.1 -> 0.1; portfolio score = 0.3, weight = 0.2 -> 0.06
        assert alert["priority_score"] == pytest.approx(0.16, rel=0.01)

    def test_article_tickers(self, db_session: Session, instrument: Instrument, article_sber: News):
        engine = AlertEngine()
        tickers = engine._article_tickers(db_session, article_sber)
        assert tickers == ["SBER"]

    def test_article_tickers_no_link(self, db_session: Session):
        engine = AlertEngine()
        orphan = News(id=999, title="orphan", source_type="rss",
                       published_at=datetime.now(timezone.utc))
        db_session.add(orphan)
        db_session.commit()
        tickers = engine._article_tickers(db_session, orphan)
        assert tickers == []


class TestAlertEngineIntegration:
    def test_process_articles_empty(self, db_session: Session):
        engine = AlertEngine()
        result = engine.process_articles(db_session, [])
        assert result == []

    def test_process_articles_no_tickers(self, db_session: Session):
        engine = AlertEngine()
        orphan = News(id=1, title="orphan", source_type="rss",
                       published_at=datetime.now(timezone.utc))
        db_session.add(orphan)
        db_session.commit()
        result = engine.process_articles(db_session, [orphan])
        assert result == []

    def test_process_articles_dedup(self, db_session: Session, instrument: Instrument):
        engine = AlertEngine()
        a1 = News(id=1, title="First", source_type="rss", source_name="Src",
                   category="MACRO", subcategory="inflation",
                   published_at=datetime.now(timezone.utc), sentiment="neutral",
                   is_relevant=True, impact_score=0.0, source_weight=0.5, source_count=1)
        a2 = News(id=2, title="Second (dup)", source_type="rss", source_name="Src",
                   category="MACRO", subcategory="inflation",
                   published_at=datetime.now(timezone.utc), sentiment="neutral",
                   is_relevant=True, impact_score=0.0, source_weight=0.5, source_count=1)
        db_session.add_all([a1, a2])
        db_session.flush()
        db_session.add_all([
            NewsInstrument(news_id=1, instrument_id=instrument.id),
            NewsInstrument(news_id=2, instrument_id=instrument.id),
        ])
        db_session.commit()
        result = engine.process_articles(db_session, [a1, a2])
        assert len(result) == 1  # second should be deduplicated

    def test_process_articles_with_portfolio(
        self, db_session: Session, instrument: Instrument,
        article_sber: News, article_gazp: News, portfolio_entry: Portfolio,
    ):
        engine = AlertEngine()
        result = engine.process_portfolio_articles(
            db_session, [article_sber, article_gazp], user_id=1,
        )
        for alert in result:
            assert "priority" in alert
            assert "priority_score" in alert

    def test_process_articles_untrained(
        self, db_session: Session, instrument: Instrument, article_sber: News,
    ):
        engine = AlertEngine()
        result = engine.process_articles(db_session, [article_sber])
        # Without trained models, everything scores 0 -> LOW
        for alert in result:
            assert alert["priority_score"] >= 0.0

    def test_train_and_process(
        self, db_session: Session, instrument: Instrument,
        instrument2: Instrument, article_sber: News,
    ):
        engine = AlertEngine()
        engine.train_anomaly(db_session)
        engine.train_impact(db_session, ["SBER"])
        result = engine.process_articles(db_session, [article_sber])
        for alert in result:
            assert alert["anomaly_score"] >= 0.0
            assert alert["predicted_return"] is not None
