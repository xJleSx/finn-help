from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

# V2-style Pydantic (already uses V2-compatible BaseModel from pydantic>=2)
from pydantic import BaseModel, Field


class TechnicalComponent(BaseModel):
    action: str = "NEUTRAL"
    confidence: float = 0.0
    score: float = 0.0


class MLComponent(BaseModel):
    signal_score: float = 0.0
    confidence: float = 0.0
    target_price: Optional[float] = None
    change_pct: Optional[float] = None


class SentimentComponent(BaseModel):
    score: float = 0.0
    source: str = "none"


class MTFComponent(BaseModel):
    direction: float = 0.0
    agreement: float = 0.0


class SignalComponents(BaseModel):
    technical: TechnicalComponent = Field(default_factory=TechnicalComponent)
    fundamental_risk: float = 0.5
    geo_risk: float = 0.0
    ml: MLComponent = Field(default_factory=MLComponent)
    sentiment: SentimentComponent = Field(default_factory=SentimentComponent)
    mtf: MTFComponent = Field(default_factory=MTFComponent)


class RiskMetrics(BaseModel):
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    calmar: float = 0.0
    omega: float = 0.0


class VolatilityRegime(BaseModel):
    regime: str = "NORMAL"
    atr_ratio: Optional[float] = None
    hv: Optional[float] = None


class FusedSignal(BaseModel):
    ticker: str
    instrument_type: str = "stock"
    action: str = "HOLD"
    confidence: float = 0.0
    weighted_score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    max_portfolio_pct: int = 10
    components: SignalComponents = Field(default_factory=SignalComponents)
    risk_metrics: Optional[RiskMetrics] = None
    volatility_regime: Optional[VolatilityRegime] = None
    trade_plan: Optional[dict[str, Any]] = None
    trends: Optional[dict[str, Any]] = None
    recent_events: list[Any] = Field(default_factory=list)
    financial_report: Optional[dict[str, Any]] = None
    financial_facts: Optional[Any] = None
    bond_offering: Optional[dict[str, Any]] = None


class SignalRecord(BaseModel):
    instrument_id: int
    date: datetime
    action: str
    confidence: float
    fused_json: dict[str, Any]


class BatchFuseRequest(BaseModel):
    tickers: list[str]
    instrument_type: str = "stock"
    user_id: Optional[str] = None
    with_ml: bool = True
