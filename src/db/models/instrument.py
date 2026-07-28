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
)
from sqlalchemy.orm import relationship

from .base import Base


class Instrument(Base):
    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    isin = Column(String(12))
    sector = Column(String(100))
    # default=None — actual type inferred from data source (MOEX/API); DDD InstrumentType enum is source of truth
    instrument_type = Column(String(20), nullable=False, default=None)
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

    __table_args__ = (
        Index("ix_fundamental_metrics_instr_date", "instrument_id", "date"),
        UniqueConstraint("instrument_id", "date", name="uq_fundamental_metrics_instr_date"),
    )


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

    def __repr__(self) -> str:
        return f"<CompanyProfile instrument_id={self.instrument_id}>"


class CorporateEvent(Base):
    """Corporate actions: dividends, buybacks, splits, additional emissions."""

    __tablename__ = "corporate_events"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)

    event_type = Column(
        String(20),
        nullable=False,
        index=True,
        comment="dividend / buyback / split / emission",
    )
    status = Column(
        String(20),
        default="announced",
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

    def __repr__(self) -> str:
        return f"<CorporateEvent {self.event_type} instr={self.instrument_id}>"


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
    rating_agency = Column(String(20), comment="Рейтинговое агентство (ACRA/ExpertRA/Moody's/S&P/Fitch)")
    rating_date = Column(Date, comment="Дата присвоения рейтинга")
    rating_scale = Column(String(10), comment="Шкала рейтинга (national/international)")
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


class BondCouponSchedule(Base):
    """Coupon schedule for bonds, fetched from MOEX ISS."""

    __tablename__ = "bond_coupon_schedules"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    coupon_date = Column(Date, nullable=False)
    coupon_value = Column(Float, nullable=False, comment="Coupon amount in RUB")
    coupon_number = Column(Integer, comment="Coupon sequence number")
    currency = Column(String(3), default="RUB")
    fix_date = Column(Date, comment="Rate fix date (for floaters)")
    face_value = Column(Float, comment="Face value at time of payment (for amortization)")
    initial_face_value = Column(Float, comment="Initial face value")
    is_amortization = Column(Boolean, default=False, comment="True if this is an amortization payment")
    paid = Column(Boolean, default=False, comment="Whether the coupon has been paid")
    extra = Column(JSON)

    instrument = relationship("Instrument", backref="coupon_schedule")

    __table_args__ = (
        UniqueConstraint("instrument_id", "coupon_date", "coupon_number", name="uq_bond_coupon"),
        Index("ix_bond_coupon_date", "coupon_date"),
    )


class BondOfferingHistory(Base):
    """Historical snapshots of bond offerings for trend analysis."""

    __tablename__ = "bond_offering_history"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False)
    offering_date = Column(Date, nullable=False)
    isin = Column(String(12), index=True)

    coupon_type = Column(String(20))
    coupon_rate = Column(Float, comment="Ставка купона % годовых")
    coupon_period_days = Column(Integer, comment="Купонный период в днях")
    yield_to_maturity = Column(Float, comment="YTM %")
    duration_years = Column(Float, comment="Дюрация в годах")
    spread_to_key_rate = Column(Float, comment="Спред к ключевой ставке")

    maturity_date = Column(Date, comment="Дата погашения")
    maturity_years = Column(Float, comment="Срок обращения в годах")
    credit_rating = Column(String(10), comment="Кредитный рейтинг")
    rating_agency = Column(String(20), comment="Рейтинговое агентство (ACRA/ExpertRA/Moody's/S&P/Fitch)")
    rating_date = Column(Date, comment="Дата присвоения рейтинга")
    rating_scale = Column(String(10), comment="Шкала рейтинга (national/international)")
    current_price_pct = Column(Float, comment="Цена в % от номинала")

    instrument = relationship("Instrument", backref="bond_offering_history")

    __table_args__ = (
        Index("ix_bond_offering_history_instr_date", "instrument_id", "snapshot_date"),
    )


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
