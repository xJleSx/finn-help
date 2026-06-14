from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
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
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Instrument(Base):
    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    isin = Column(String(12))
    sector = Column(String(100))
    instrument_type = Column(String(20), nullable=False, default="stock")
    lot_size = Column(Integer, default=1)
    currency = Column(String(3), default="RUB")
    moex_uid = Column(String(50))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    prices = relationship("Price", back_populates="instrument", lazy="dynamic")
    dividends = relationship("Dividend", back_populates="instrument", lazy="dynamic")
    indicators = relationship("Indicator", back_populates="instrument", lazy="dynamic")
    predictions = relationship("Prediction", back_populates="instrument", lazy="dynamic")
    signals = relationship("Signal", back_populates="instrument", lazy="dynamic")


class Price(Base):
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)

    instrument = relationship("Instrument", back_populates="prices")

    __table_args__ = (
        UniqueConstraint("instrument_id", "date", name="uq_price_date"),
        Index("ix_prices_instrument_date", "instrument_id", "date"),
    )


class Dividend(Base):
    __tablename__ = "dividends"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="RUB")
    tax_rate = Column(Float)

    instrument = relationship("Instrument", back_populates="dividends")

    __table_args__ = (UniqueConstraint("instrument_id", "date", "amount", name="uq_dividend"),)


class Indicator(Base):
    __tablename__ = "indicators"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(Date, nullable=False)
    rsi = Column(Float)
    macd_line = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)
    sma_20 = Column(Float)
    sma_50 = Column(Float)
    sma_200 = Column(Float)
    bb_upper = Column(Float)
    bb_lower = Column(Float)
    bb_mid = Column(Float)
    volume_sma_20 = Column(Float)
    atr = Column(Float)

    instrument = relationship("Instrument", back_populates="indicators")

    __table_args__ = (
        UniqueConstraint("instrument_id", "date", name="uq_indicator"),
        Index("ix_indicators_instrument_date", "instrument_id", "date"),
    )


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    model_name = Column(String(50), nullable=False)
    date = Column(Date, nullable=False)
    target_price = Column(Float)
    confidence = Column(Float)
    features_json = Column(JSON)

    instrument = relationship("Instrument", back_populates="predictions")


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(DateTime, default=func.now(), nullable=False)
    action = Column(String(10), nullable=False)
    confidence = Column(Float)
    technical_json = Column(JSON)
    fundamental_json = Column(JSON)
    geo_json = Column(JSON)
    fused_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())

    instrument = relationship("Instrument", back_populates="signals")


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True)
    url = Column(String(1024), unique=True)
    title = Column(String(512), nullable=False)
    summary = Column(Text)
    content_hash = Column(String(64))
    sentiment_score = Column(Float)
    source_type = Column(String(10), nullable=False)
    source_name = Column(String(100))
    published_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())

    instruments = relationship("NewsInstrument", back_populates="news")


class NewsInstrument(Base):
    __tablename__ = "news_instruments"

    news_id = Column(Integer, ForeignKey("news.id"), primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), primary_key=True)

    news = relationship("News", back_populates="instruments")
    instrument = relationship("Instrument")


class GeoRiskScore(Base):
    __tablename__ = "geo_risk_scores"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False)
    score = Column(Float, nullable=False)
    components_json = Column(JSON)
    sources_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())


class Portfolio(Base):
    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), unique=True, nullable=False)
    quantity = Column(Float, nullable=False, default=0)
    avg_price = Column(Float)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    instrument = relationship("Instrument")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    type = Column(String(4), nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    date = Column(DateTime, default=func.now())
    commission = Column(Float, default=0.0)

    instrument = relationship("Instrument")


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


class UserSetting(Base):
    __tablename__ = "user_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text)
