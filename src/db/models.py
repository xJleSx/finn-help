from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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
    text as sa_text,
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
    exchange = Column(String(10), default="MOEX")
    figi = Column(String(50), index=True)
    moex_uid = Column(String(50))
    nominal = Column(Float, comment="Face value for bonds (руб), 0 for non-bonds")
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
    action = Column(String(20), nullable=False)
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


class GeoRiskScore(Base):
    __tablename__ = "geo_risk_scores"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False)
    score = Column(Float, nullable=False)
    components_json = Column(JSON)
    sources_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="user")
    is_active = Column(Boolean, default=True)
    risk_profile = Column(String(20), default="balanced")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Portfolio(Base):
    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=0)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    quantity = Column(Float, nullable=False, default=0)
    avg_price = Column(Float)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    instrument = relationship("Instrument")
    user = relationship("User")

    __table_args__ = (UniqueConstraint("user_id", "instrument_id", name="uq_user_portfolio"),)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=0)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    tx_type = Column("type", String(4), nullable=False)
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


class UserSetting(Base):
    __tablename__ = "user_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    notify_signal = Column(Boolean, default=True)
    notify_daily = Column(Boolean, default=True)
    notify_geo = Column(Boolean, default=False)
    notify_dividend = Column(Boolean, default=False)
    notify_trade = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("user_id", name="uq_subscription_user"),)


class AuthorSubscription(Base):
    __tablename__ = "author_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False)
    author_nick = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "author_nick", name="uq_user_author_sub"),
        Index("ix_author_sub_author", "author_nick"),
    )


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_user_favorite_ticker"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    type = Column(String(20), nullable=False)
    title = Column(String(200))
    message = Column(Text, nullable=False)
    data_json = Column(JSON)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "read"),
        Index("ix_notifications_created", "created_at"),
    )


class ChannelPreference(Base):
    __tablename__ = "channel_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    enabled = Column(Boolean, default=True)
    min_severity = Column(String(20), default="LOW")
    quiet_hours_start = Column(String(5), nullable=True)
    quiet_hours_end = Column(String(5), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "channel", name="uq_user_channel"),
    )


class MutedAlert(Base):
    __tablename__ = "muted_alerts"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    alert_type = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "ticker", "alert_type", name="uq_user_muted_alert"),
    )


class AlertLog(Base):
    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False, index=True)
    severity = Column(Float, nullable=False, default=0.0)
    title = Column(String(512), nullable=False)
    message = Column(Text)
    created_at = Column(DateTime, default=func.now(), index=True)
    read = Column(Boolean, default=False)
    user_id = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_alert_log_ticker_created", "ticker", "created_at"),
        Index("ix_alert_log_type_created", "alert_type", "created_at"),
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


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)  # BUY / SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=True)
    order_type = Column(String(10), default="market")  # market / limit
    status = Column(
        String(30), default="pending"
    )  # pending / approved / submitted / filled / partial / rejected / cancelled
    mode = Column(String(20), default="manual")  # dry_run / manual / auto
    reason = Column(Text, default="")
    order_id_ext = Column(String(100), nullable=True)  # external order ID
    figi = Column(String(50), nullable=True)
    commission = Column(Float, nullable=True)
    executed_price = Column(Float, nullable=True)
    executed_quantity = Column(Integer, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_created", "created_at"),
    )


class TradeLog(Base):
    __tablename__ = "trade_log"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    ticker = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    commission = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)  # realised P&L
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_trade_log_tkr", "ticker"),
        Index("ix_trade_log_ct", "created_at"),
    )


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


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    taken_at = Column(DateTime(timezone=True), nullable=False)
    period = Column(String(10), nullable=False, index=True)  # daily / weekly / monthly

    price = Column(Float)
    rsi = Column(Float)
    macd_line = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)
    sma_20 = Column(Float)
    sma_50 = Column(Float)
    sma_200 = Column(Float)
    signal_action = Column(String(20))
    signal_score = Column(Float)
    signal_confidence = Column(Float)

    delta_price_pct = Column(Float)
    delta_score = Column(Float)
    delta_rsi = Column(Float)
    delta_action_changed = Column(Boolean)

    market_score_avg = Column(Float)
    social_score_avg = Column(Float)
    geo_score = Column(Float)

    __table_args__ = (
        Index("ix_snapshot_instr_period", "instrument_id", "period"),
        Index("ix_snapshot_taken", "taken_at"),
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


class FundamentalMetric(Base):
    __tablename__ = "fundamental_metrics"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    period = Column(String(10), default="annual")  # annual / quarterly / ttm

    market_cap = Column(Float, comment="Рыночная капитализация (RUB)")
    shares_outstanding = Column(BigInteger, comment="Количество акций в обращении")
    pe_ratio = Column(Float, comment="P/E")
    pb_ratio = Column(Float, comment="P/B")
    roe = Column(Float, comment="ROE %")
    eps = Column(Float, comment="EPS (RUB)")
    debt_equity = Column(Float, comment="Debt/Equity")
    book_value = Column(Float, comment="Балансовая стоимость на акцию (RUB)")
    revenue = Column(Float, comment="Выручка (RUB)")
    net_income = Column(Float, comment="Чистая прибыль (RUB)")

    extra = Column(JSON, comment="Дополнительные метрики (свободный формат)")

    instrument = relationship("Instrument", backref="fundamental_metrics")

    __table_args__ = (Index("ix_fundamental_metrics_instr_date", "instrument_id", "date"),)


class FinancialReport(Base):
    __tablename__ = "financial_reports"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    report_date = Column(Date, nullable=False, index=True)
    period_type = Column(String(10), nullable=False)
    currency = Column(String(3), default="RUB")
    source = Column(String(50), default="manual")

    net_profit = Column(Float, comment="Чистая прибыль")
    revenue = Column(Float, comment="Выручка")
    net_interest_income = Column(Float, comment="Чистые процентные доходы (для банков)")
    operating_income = Column(Float, comment="Операционные доходы")
    total_assets = Column(Float, comment="Активы")
    total_liabilities = Column(Float, comment="Обязательства")
    total_equity = Column(Float, comment="Собственный капитал")
    loan_portfolio = Column(Float, comment="Кредитный портфель (для банков)")
    customer_deposits = Column(Float, comment="Средства клиентов (для банков)")
    cost_income_ratio = Column(Float, comment="CIR")
    roe = Column(Float, comment="ROE %")
    roa = Column(Float, comment="ROA %")
    net_margin = Column(Float, comment="Чистая процентная маржа")
    npl_ratio = Column(Float, comment="NPL %")
    provision_coverage = Column(Float, comment="Покрытие резервами")
    capital_adequacy = Column(Float, comment="Норматив достаточности капитала")

    extra = Column(JSON)

    instrument = relationship("Instrument", backref="financial_reports")

    __table_args__ = (
        UniqueConstraint("instrument_id", "report_date", "period_type", name="uq_fin_report_date"),
        Index("ix_financial_reports_instr_date", "instrument_id", "report_date"),
    )


class BondOffering(Base):
    __tablename__ = "bond_offerings"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    offering_date = Column(Date, nullable=False)
    isin = Column(String(12), index=True)

    coupon_type = Column(String(20), nullable=False)
    coupon_rate = Column(Float, comment="Ставка купона % годовых")
    coupon_period_days = Column(Integer, comment="Купонный период в днях")
    spread_to_key_rate = Column(Float, comment="Спред к ключевой ставке")
    yield_to_maturity = Column(Float, comment="YTM %")
    duration_years = Column(Float, comment="Дюрация в годах")

    maturity_date = Column(Date, comment="Дата погашения")
    maturity_years = Column(Float, comment="Срок обращения в годах")
    credit_rating = Column(String(10), comment="Кредитный рейтинг")
    volume = Column(Float, comment="Объём выпуска (RUB)")

    has_amortization = Column(Boolean, default=False)
    has_offer = Column(Boolean, default=False)
    min_lot_rub = Column(Float, comment="Минимальная заявка (RUB)")
    qual_investor_only = Column(Boolean, default=False)
    nominal_price = Column(Float, comment="Номинальная цена")
    current_price_pct = Column(Float, comment="Цена в % от номинала")

    extra = Column(JSON)

    instrument = relationship("Instrument", backref="bond_offerings")

    __table_args__ = (
        UniqueConstraint("instrument_id", "isin", name="uq_bond_offering_isin"),
        Index("ix_bond_offerings_instr", "instrument_id"),
    )


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


# Phase 3: Sector Risk History
class SectorRiskHistory(Base):
    __tablename__ = "sector_risk_history"

    id = Column(Integer, primary_key=True)
    sector = Column(String(100), nullable=False)
    date = Column(Date, nullable=False)
    risk_score = Column(Float, nullable=False)
    components_json = Column(JSON)
    article_count = Column(Integer)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("sector", "date", name="uq_sector_risk_date"),)


# Phase 4: Company Risk History
class CompanyRiskHistory(Base):
    __tablename__ = "company_risk_history"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(Date, nullable=False)
    risk_score = Column(Float, nullable=False)
    sector_risk = Column(Float)
    geopolitical_risk = Column(Float)
    macro_risk = Column(Float)
    company_specific_risk = Column(Float)
    components_json = Column(JSON)
    article_count = Column(Integer)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("instrument_id", "date", name="uq_company_risk_date"),
        Index("ix_company_risk_instrument_date", "instrument_id", "date"),
    )


# Phase 5: Geopolitical Risk History
class GeopoliticalRiskHistory(Base):
    __tablename__ = "geopolitical_risk_history"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    risk_score = Column(Float, nullable=False)
    sanctions_score = Column(Float)
    conflict_score = Column(Float)
    trade_war_score = Column(Float)
    diplomacy_score = Column(Float)
    components_json = Column(JSON)
    sources_json = Column(JSON)
    article_count = Column(Integer)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("date", name="uq_geopolitical_risk_date"),)


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


class CompanyProfile(Base):
    """Full company profile and description."""

    __tablename__ = "company_profiles"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, unique=True, index=True)

    description = Column(Text, comment="Краткое описание бизнеса")
    website = Column(String(255), comment="Официальный сайт")
    employees = Column(Integer, comment="Количество сотрудников")
    founded_year = Column(Integer, comment="Год основания")
    industry = Column(String(100), comment="Отрасль")
    industry_description = Column(Text, comment="Описание отрасли")

    registrar = Column(String(100), comment="Регистратор")
    auditor = Column(String(100), comment="Аудитор")
    state_reg_number = Column(String(50), comment="ОГРН")
    tax_id = Column(String(50), comment="ИНН")

    extra = Column(JSON)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    instrument = relationship("Instrument", backref="profile", uselist=False)

    def __repr__(self):
        return f"<CompanyProfile instrument_id={self.instrument_id}>"


class CorporateEvent(Base):
    """Corporate actions: dividends, buybacks, splits, additional emissions."""

    __tablename__ = "corporate_events"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)

    event_type = Column(
        String(20), nullable=False, index=True,
        comment="dividend / buyback / split / emission",
    )
    status = Column(
        String(20), default="announced",
        comment="announced / approved / executed / cancelled",
    )

    announcement_date = Column(Date, index=True, comment="Дата объявления")
    ex_date = Column(Date, comment="Экс-дата (для дивидендов)")
    record_date = Column(Date, comment="Дата фиксации реестра")
    payment_date = Column(Date, comment="Дата выплаты/исполнения")

    description = Column(String(500), comment="Описание события")

    # For dividends
    dividend_amount = Column(Float, comment="Сумма дивиденда на акцию (RUB)")
    dividend_currency = Column(String(3), default="RUB")
    dividend_tax_rate = Column(Float, comment="Ставка налога на дивиденды")

    # For buyback
    buyback_volume = Column(Float, comment="Объём байбэка (RUB)")
    buyback_shares = Column(Float, comment="Количество акций к выкупу")
    buyback_price = Column(Float, comment="Цена выкупа (RUB)")

    # For splits / consolidation
    split_ratio_from = Column(Integer, comment="Было акций")
    split_ratio_to = Column(Integer, comment="Стало акций")

    # For additional emission
    emission_volume = Column(Float, comment="Объём доп. эмиссии (RUB)")
    emission_shares = Column(Float, comment="Количество новых акций")
    emission_price = Column(Float, comment="Цена размещения (RUB)")

    extra = Column(JSON)
    created_at = Column(DateTime, default=func.now())

    instrument = relationship("Instrument", backref="corporate_events")

    __table_args__ = (
        Index("ix_corporate_event_type_date", "event_type", "announcement_date"),
        Index("ix_corporate_event_instr_date", "instrument_id", "announcement_date"),
    )

    def __repr__(self):
        return f"<CorporateEvent {self.event_type} instr={self.instrument_id}>"
