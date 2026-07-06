from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Index,
)
from sqlalchemy.orm import relationship

from .base import Base


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True)
    url = Column(String(1024), unique=True)
    title = Column(String(512), nullable=False)
    summary = Column(Text)
    content_hash = Column(String(64))
    sentiment_score = Column(Float)
    sentiment_weighted = Column(Float)
    sentiment_bert_score = Column(Float)
    source_weight = Column(Float)
    source_type = Column(String(10), nullable=False)
    source_name = Column(String(100))
    published_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())

    # Phase 1: Categorization & Deduplication
    category = Column(String(50), default="UNCLASSIFIED", index=True)
    subcategory = Column(String(100), index=True)
    sentiment = Column(String(20))
    impact_score = Column(Float, default=0.0)
    event_id = Column(Integer, ForeignKey("news_events.id"), index=True)
    is_relevant = Column(Boolean, default=True, index=True)
    embedding = Column(JSON)  # Vector embedding for deduplication
    source_count = Column(Integer, default=1)  # Number of sources reporting same event
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    instruments = relationship("NewsInstrument", back_populates="news")
    event = relationship("NewsEvent", back_populates="articles")


class NewsEvent(Base):
    __tablename__ = "news_events"

    id = Column(Integer, primary_key=True)
    title = Column(String(512), nullable=False)
    summary = Column(Text)
    category = Column(String(50), nullable=False, index=True)
    subcategory = Column(String(100), index=True)
    impact_score = Column(Float, default=0.0)
    sentiment = Column(String(20))
    article_count = Column(Integer, default=1)
    published_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    articles = relationship("News", back_populates="event")


class NewsInstrument(Base):
    __tablename__ = "news_instruments"

    news_id = Column(Integer, ForeignKey("news.id"), primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), primary_key=True)

    news = relationship("News", back_populates="instruments")
    instrument = relationship("Instrument")


# Phase 3: Sector Impact Tracking
class NewsSectorImpact(Base):
    __tablename__ = "news_sector_impacts"

    id = Column(Integer, primary_key=True)
    news_id = Column(Integer, ForeignKey("news.id"), nullable=False, index=True)
    sector = Column(String(100), nullable=False, index=True)
    impact_type = Column(String(50), nullable=False, index=True)
    impact_score = Column(Float, nullable=False)
    intensity = Column(Float)
    created_at = Column(DateTime, default=func.now())


# Phase 4: Company Impact Tracking
class NewsCompanyImpact(Base):
    __tablename__ = "news_company_impacts"

    id = Column(Integer, primary_key=True)
    news_id = Column(Integer, ForeignKey("news.id"), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    impact_type = Column(String(50), nullable=False)
    impact_score = Column(Float, nullable=False)
    intensity = Column(Float)
    created_at = Column(DateTime, default=func.now())
