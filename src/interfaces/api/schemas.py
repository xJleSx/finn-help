from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    checks: Optional[dict[str, str]] = None
    components: dict[str, Any]


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    username: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    risk_profile: str
    is_active: bool


class PortfolioPosition(BaseModel):
    id: int
    ticker: str
    quantity: float
    avg_price: float
    current_price: float
    value: float
    profit_pct: float


class PortfolioAddResponse(BaseModel):
    status: str


class AllocationItem(BaseModel):
    ticker: str
    name: str
    amount: float
    reason: str
    expected_yield: float
    sector: str
    last_price: Optional[float] = None
    risk: dict[str, Any]


class AllocationCategory(BaseModel):
    label: str
    budget: float
    items: list[AllocationItem]


class AllocationResponse(BaseModel):
    capital: float
    total_allocated: float
    reserve: float
    plan: dict[str, AllocationCategory]
    projected_monthly_yield: float
    projected_monthly_pct: float
    existing_portfolio: list[dict[str, Any]]
    sector_allocation: dict[str, float]


class InstrumentListItem(BaseModel):
    id: int
    ticker: str
    full_name: Optional[str] = None
    sector: Optional[str] = None
    type: str
    last_price: Optional[float] = None
    last_date: Optional[str] = None


class InstrumentDetail(BaseModel):
    id: int
    ticker: str
    full_name: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    type: str
    lot_size: Optional[int] = None
    currency: Optional[str] = None


class PriceData(BaseModel):
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None


class IndicatorData(BaseModel):
    date: str
    rsi: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_mid: Optional[float] = None
    volume_sma_20: Optional[float] = None
    atr: Optional[float] = None


class EntryZone(BaseModel):
    low: float
    high: float
    current: float


class TargetItem(BaseModel):
    level: float
    type: str
    return_pct: float
    rr: float


class TradePlanResponse(BaseModel):
    ticker: str
    profile: str
    current_price: float
    entry_zone: EntryZone
    targets: list[TargetItem]
    stop_loss: float
    trailing_after: float
    risk_reward: float


class AdviceResponse(BaseModel):
    signal: dict[str, Any]
    advice: str
    user_id: Optional[int] = None


class AskResponse(BaseModel):
    answer: str
    user_id: Optional[int] = None
    risk_profile: str


class NewsItem(BaseModel):
    id: int
    title: Optional[str] = None
    summary: str
    source: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[str] = None


class GeoRiskItem(BaseModel):
    date: str
    score: float
    components: Optional[dict[str, Any]] = None


class PriceTargetAlert(BaseModel):
    ticker: str
    current_price: float
    target_price: float
    target_type: str
    triggered_pct: float


class DivergenceAlert(BaseModel):
    ticker: str
    divergence_type: str
    indicator: str
    strength: float


class RebalanceAlert(BaseModel):
    ticker: str
    current_pct: float
    target_pct: float
    deviation_pct: float
    reason: str


class ScenarioItem(BaseModel):
    name: str
    loss_pct: float
    loss: float
    total_after: float
    var_95: float | None = None


class MonteCarloItem(BaseModel):
    var_95: float
    cvar_95: float
    var_99: float
    mean_return: float


class ScenarioResponse(BaseModel):
    total: float
    positions: list[dict[str, Any]]
    scenarios: list[ScenarioItem]
    monte_carlo: MonteCarloItem | None = None
    bootstrap: MonteCarloItem | None = None
    sector_breakdown: dict[str, float]


class AlertItem(BaseModel):
    news_id: int
    ticker: str
    title: str
    category: str
    subcategory: str
    source_name: str
    published_at: str
    priority: str
    priority_score: float
    anomaly_score: float
    predicted_return: float
    impact_confidence: float
    in_portfolio: bool
    reason: str


class AlertResponse(BaseModel):
    alerts: list[AlertItem]


class FeatureImportance(BaseModel):
    feature: str
    importance: float


class ImpactAttributionResponse(BaseModel):
    news_id: int
    ticker: str
    feature_importances: list[FeatureImportance]
