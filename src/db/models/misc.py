from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Index,
    text as sa_text,
)

from .base import Base


class Relation(Base):
    __tablename__ = "relations"

    id = Column(Integer, primary_key=True)
    source_type = Column(String(50), nullable=False)
    source_id = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(String(100), nullable=False)
    relation_type = Column(String(50), nullable=False)
    weight = Column(Float, default=1.0)
    metadata_json = Column(JSON)

    __table_args__ = (
        Index("ix_relations_source", "source_type", "source_id"),
        Index("ix_relations_target", "target_type", "target_id"),
    )


class MacroIndicator(Base):
    __tablename__ = "macro_indicators"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    indicator_type = Column(String(50), nullable=False)
    value = Column(Float, nullable=False)
    source = Column(String(50))

    __table_args__ = (
        UniqueConstraint("date", "indicator_type", name="uq_macro_date_type"),
        Index("ix_macro_type_date", "indicator_type", "date"),
    )


class AltDataPoint(Base):
    __tablename__ = "alt_data_points"

    id = Column(Integer, primary_key=True)
    source_name = Column(String(50), nullable=False, index=True)
    indicator_name = Column(String(100), nullable=False)
    value = Column(Float, nullable=False)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("source_name", "indicator_name", "date", name="uq_alt_data_point"),
        Index("ix_alt_data_source_date", "source_name", "date"),
    )


class FeatureCache(Base):
    __tablename__ = "feature_cache"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    feature_type = Column(String(50), nullable=False)
    date = Column(Date, nullable=False)
    value_json = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, server_default=sa_text("1"))
    ttl_hours = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("ticker", "feature_type", "date", name="uq_feature_cache"),
        Index("ix_feature_ticker_type", "ticker", "feature_type"),
    )


class MarketEvent(Base):
    __tablename__ = "market_events"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    severity = Column(Float, nullable=False, default=0.5)
    market_impact_pct = Column(Float)
    sector_impacts_json = Column(JSON)
    indicators_before_json = Column(JSON)
    indicators_after_json = Column(JSON)
    source = Column(String(50), default="synthetic")
    source_news_id = Column(Integer, ForeignKey("news.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (Index("ix_market_events_date_type", "date", "event_type"),)


class ModelFeedback(Base):
    __tablename__ = "model_feedback"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    model_name = Column(String(50), nullable=False, index=True)
    predicted_return = Column(Float, nullable=False)
    actual_return = Column(Float, nullable=False)
    prediction_date = Column(DateTime, nullable=False)
    horizon_days = Column(Integer, nullable=False)
    features_hash = Column(String(64), default="")
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_model_feedback_ticker_name", "ticker", "model_name"),
        Index("ix_model_feedback_created", "created_at"),
    )


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)

    total_buy = Column(Integer, default=0)
    total_sell = Column(Integer, default=0)
    total_hold = Column(Integer, default=0)
    market_score_avg = Column(Float)
    market_score_trend = Column(String(10))  # up / down / flat

    portfolio_signals = Column(JSON)  # [{"ticker":"SBER","action":"BUY","confidence":0.72,"score_delta":0.15},...]

    report_text = Column(Text)
