from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=0)
    balance = Column(Float, nullable=False, default=1_000_000.0)
    initial_balance = Column(Float, nullable=False, default=1_000_000.0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User")


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=0)
    ticker = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)  # BUY / SELL
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    executed_price = Column(Float, nullable=True)
    commission = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    status = Column(String(20), default="filled")  # filled / partial / rejected
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_paper_orders_user", "user_id"),
        Index("ix_paper_orders_ticker", "ticker"),
        Index("ix_paper_orders_created", "created_at"),
    )


class PaperTradeLog(Base):
    __tablename__ = "paper_trade_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=0)
    order_id = Column(Integer, ForeignKey("paper_orders.id"), nullable=True)
    ticker = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    commission = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    balance_before = Column(Float, nullable=True)
    balance_after = Column(Float, nullable=True)
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_paper_trade_log_user", "user_id"),
        Index("ix_paper_trade_log_ticker", "ticker"),
    )
