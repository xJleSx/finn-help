from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from .base import Base


class SocialPost(Base):
    __tablename__ = "social_posts"

    id = Column(Integer, primary_key=True)
    source = Column(String(20), nullable=False, index=True)
    external_id = Column(String(255))
    author_nick = Column(String(255), nullable=False, index=True)
    author_id = Column(String(255))
    text = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True))
    url = Column(String(1024))
    tickers_mentioned = Column(JSON)
    raw_json = Column(JSON)
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime(timezone=True))
    deferred = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_social_post_source_ext"),
        Index("ix_social_posts_author", "source", "author_nick"),
        Index("ix_social_posts_processed", "processed"),
    )


class AuthorProfile(Base):
    __tablename__ = "author_profiles"

    id = Column(Integer, primary_key=True)
    source = Column(String(20), nullable=False)
    author_nick = Column(String(255), nullable=False)
    followers_count = Column(Integer, default=0)
    year_yield = Column(Float)
    month_yield = Column(Float)
    strategy_description = Column(Text)
    manual_reliability_score = Column(Float, default=0.5)
    last_yield_update = Column(DateTime(timezone=True))
    last_fetched = Column(DateTime(timezone=True))
    cache_json = Column(JSON)

    __table_args__ = (UniqueConstraint("source", "author_nick", name="uq_author_profile_source_nick"),)


class SentimentSignal(Base):
    __tablename__ = "sentiment_signals"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("social_posts.id"), nullable=True)
    ticker = Column(String(20), index=True)
    bullish_score = Column(Float, default=0.0)
    bearish_score = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    composite_score = Column(Float, default=0.0)
    llm_reasoning = Column(Text)
    source_weight = Column(Float, default=0.5)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (Index("ix_sentiment_signals_ticker_date", "ticker", "created_at"),)
