from sqlalchemy import (
    Boolean,
    Column,
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
)
from sqlalchemy.orm import relationship

from .base import Base


class Portfolio(Base):
    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    tx_type = Column("type", String(4), nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    date = Column(DateTime, default=func.now())
    commission = Column(Float, default=0.0)

    instrument = relationship("Instrument")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)  # BUY / SELL / SHORT / COVER
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=True)
    order_type = Column(String(10), default="market")  # market / limit / ioc / fok
    time_in_force = Column(String(10), default="day")  # day / ioc / fok / gtc
    status = Column(String(30), default="pending")  # pending / approved / submitted / filled / partial / rejected / cancelled / expired
    mode = Column(String(20), default="manual")  # dry_run / manual / auto
    reason = Column(Text, default="")
    order_id_ext = Column(String(100), nullable=True)  # external order ID
    figi = Column(String(50), nullable=True)
    commission = Column(Float, nullable=True)
    executed_price = Column(Float, nullable=True)
    executed_quantity = Column(Integer, nullable=True)
    filled_quantity = Column(Integer, default=0)
    remaining_quantity = Column(Integer, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    parent_order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    is_short = Column(Boolean, default=False)
    margin_used = Column(Float, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    fills = relationship("OrderFill", back_populates="order", lazy="dynamic")

    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_created", "created_at"),
        Index("ix_orders_ticker", "ticker"),
    )


class OrderFill(Base):
    __tablename__ = "order_fills"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    commission = Column(Float, nullable=True)
    filled_at = Column(DateTime, default=func.now())

    order = relationship("Order", back_populates="fills")

    __table_args__ = (Index("ix_order_fills_order", "order_id"),)


class ShortPosition(Base):
    __tablename__ = "short_positions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    avg_price = Column(Float, nullable=True)
    margin_held = Column(Float, nullable=True)
    borrow_rate = Column(Float, default=0.0)
    opened_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_short_position_user_ticker"),
        Index("ix_short_positions_ticker", "ticker"),
    )


class MarginAccount(Base):
    __tablename__ = "margin_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    total_loan = Column(Float, default=0.0)
    margin_used = Column(Float, default=0.0)
    margin_limit = Column(Float, default=0.0)
    leverage = Column(Float, default=1.0)
    status = Column(String(20), default="safe")  # safe / warning / margin_call / liquidation
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User")

    __table_args__ = (UniqueConstraint("user_id", name="uq_margin_account_user"),)


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


class ComplianceEvent(Base):
    __tablename__ = "compliance_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type = Column(String(50), nullable=False)  # aml_flag / position_limit / margin_call / short_limit
    ticker = Column(String(20), nullable=True)
    details = Column(Text, nullable=True)
    severity = Column(String(20), default="info")  # info / warning / critical
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User")

    __table_args__ = (
        Index("ix_compliance_events_user", "user_id"),
        Index("ix_compliance_events_type", "event_type"),
    )


class TaxReportRecord(Base):
    __tablename__ = "tax_report_records"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    year = Column(Integer, nullable=False)
    total_pnl = Column(Float, default=0.0)
    total_dividends = Column(Float, default=0.0)
    total_tax_due = Column(Float, default=0.0)
    tax_paid = Column(Float, default=0.0)
    report_data = Column(JSON)
    generated_at = Column(DateTime, default=func.now())

    user = relationship("User")

    __table_args__ = (UniqueConstraint("user_id", "year", name="uq_tax_report_user_year"),)
