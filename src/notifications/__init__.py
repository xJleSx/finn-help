from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SignalNotification:
    ticker: str
    action: str
    prev_action: Optional[str]
    confidence: float
    weighted_score: float
    reasons: list[str]
    max_portfolio_pct: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GeoRiskNotification:
    score: float
    level: str
    signals: list[str]
    prev_score: Optional[float]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DividendNotification:
    ticker: str
    amount: float
    ex_date: Optional[str]
    yield_pct: Optional[float]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DailySummaryNotification:
    date: str
    total_signals: int
    buy_signals: int
    sell_signals: int
    geo_risk: float
    portfolio_value: Optional[float]
    top_picks: list[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PriceTargetAlert:
    ticker: str
    current_price: float
    target_price: float
    target_type: str  # take_profit, stop_loss
    triggered_pct: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DivergenceAlert:
    ticker: str
    divergence_type: str  # bullish, bearish
    indicator: str  # rsi, macd
    price_direction: str
    indicator_direction: str
    strength: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RebalanceAlert:
    ticker: str
    current_pct: float
    target_pct: float
    deviation_pct: float
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
