from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"
    FOK = "fok"


class TimeInForce(str, Enum):
    DAY = "day"
    IOC = "ioc"
    FOK = "fok"
    GTC = "gtc"


class OrderStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    SIMULATED = "simulated"
    PENDING_APPROVAL = "pending_approval"
    FAILED = "failed"
    EXPIRED = "expired"


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SHORT = "SHORT"
    COVER = "COVER"


class TradeMode(str, Enum):
    DRY_RUN = "dry_run"
    MANUAL = "manual"
    AUTO = "auto"


@dataclass
class Fill:
    quantity: int
    price: float
    commission: float = 0.0
    filled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class MarginRequirements:
    initial_margin: float = 0.0
    maintenance_margin: float = 0.0
    margin_call_price: float = 0.0
    leverage: float = 1.0
    liquidation_price: float = 0.0
    portfolio_value: float = 0.0
    loan_amount: float = 0.0
    free_cash: float = 0.0
    margin_used_pct: float = 0.0
    margin_status: str = "safe"


@dataclass
class ShortPosition:
    ticker: str
    quantity: int
    avg_price: float
    margin_required: float = 0.0
    borrow_rate: float = 0.0


@dataclass
class TaxLot:
    id: str = ""
    ticker: str = ""
    quantity: int = 0
    buy_price: float = 0.0
    buy_date: str = ""
    sell_price: float = 0.0
    sell_date: str = ""
    pnl: float = 0.0
    tax_rate: float = 0.13
    tax_amount: float = 0.0
    holding_days: int = 0
    is_short_term: bool = True


@dataclass
class TaxReport:
    year: int = 2026
    total_realized_pnl: float = 0.0
    total_dividends: float = 0.0
    total_tax_due: float = 0.0
    tax_paid: float = 0.0
    lots: list[TaxLot] = field(default_factory=list)
    dividends: list[dict[str, Any]] = field(default_factory=list)
    broker_commission_total: float = 0.0
    currency: str = "RUB"


@dataclass
class ComplianceCheck:
    passed: bool = True
    checks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)


@dataclass
class AMLRecord:
    user_id: int = 0
    ticker: str = ""
    volume_rub: float = 0.0
    pattern: str = ""
    risk_score: float = 0.0
    flagged: bool = False
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class LeverageInfo:
    portfolio_value: float = 0.0
    total_loan: float = 0.0
    leverage_ratio: float = 1.0
    margin_call_level: float = 0.0
    liquidation_level: float = 0.0
    free_margin: float = 0.0
    used_margin: float = 0.0
    margin_status: str = "safe"
