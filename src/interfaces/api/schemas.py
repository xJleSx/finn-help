from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(..., description="Service health status: ok | degraded | unhealthy")
    checks: Optional[dict[str, str]] = Field(None, description="Non-critical warnings")
    components: dict[str, Any] = Field(..., description="Health state of each subsystem")


class AuthTokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token (30-day expiry)")
    token_type: str = Field(..., description="Token type (bearer)")
    user_id: int = Field(..., description="User identifier")
    username: str = Field(..., description="Display name")


class RefreshTokenResponse(BaseModel):
    access_token: str = Field(..., description="New JWT access token")
    token_type: str = Field(..., description="Token type (bearer)")


class UserResponse(BaseModel):
    id: int = Field(..., description="User identifier")
    username: str = Field(..., description="Display name")
    email: Optional[str] = Field(None, description="Email address")
    role: str = Field(..., description="User role")
    risk_profile: str = Field(..., description="Risk profile")
    is_active: bool = Field(..., description="Whether account is active")


class PortfolioPosition(BaseModel):
    id: int = Field(..., description="Position identifier")
    ticker: str = Field(..., description="Instrument ticker")
    quantity: float = Field(..., description="Shares held")
    avg_price: float = Field(..., description="Average entry price")
    current_price: float = Field(..., description="Latest market price")
    value: float = Field(..., description="Current market value")
    profit_pct: float = Field(..., description="Profit / loss percentage")


class PortfolioAddResponse(BaseModel):
    status: str = Field(..., description="Operation status")


class AllocationItem(BaseModel):
    ticker: str = Field(..., description="Instrument ticker")
    name: str = Field(..., description="Instrument full name")
    amount: float = Field(..., description="Recommended investment amount")
    reason: str = Field(..., description="Investment rationale")
    expected_yield: float = Field(..., description="Expected annual yield")
    sector: str = Field(..., description="Economic sector")
    last_price: Optional[float] = Field(None, description="Latest market price")
    risk: dict[str, Any] = Field(..., description="Risk assessment")


class AllocationCategory(BaseModel):
    label: str = Field(..., description="Category label")
    budget: float = Field(..., description="Budget allocated")
    items: list[AllocationItem] = Field(..., description="Recommended instruments")


class AllocationResponse(BaseModel):
    capital: float = Field(..., description="Total available capital")
    total_allocated: float = Field(..., description="Sum of all allocations")
    reserve: float = Field(..., description="Unallocated reserve")
    plan: dict[str, AllocationCategory] = Field(..., description="Allocation by category")
    projected_monthly_yield: float = Field(..., description="Projected monthly income")
    projected_monthly_pct: float = Field(..., description="Projected monthly yield %")
    existing_portfolio: list[dict[str, Any]] = Field(..., description="Current holdings")
    sector_allocation: dict[str, float] = Field(..., description="Target sector allocation")


class InstrumentListItem(BaseModel):
    id: int = Field(..., description="Instrument ID")
    ticker: str = Field(..., description="Ticker symbol")
    full_name: Optional[str] = Field(None, description="Full instrument name")
    sector: Optional[str] = Field(None, description="Economic sector")
    type: str = Field(..., description="Instrument type")
    last_price: Optional[float] = Field(None, description="Latest closing price")
    last_date: Optional[str] = Field(None, description="Date of last price")


class InstrumentDetail(BaseModel):
    id: int = Field(..., description="Instrument ID")
    ticker: str = Field(..., description="Ticker symbol")
    full_name: Optional[str] = Field(None, description="Full instrument name")
    isin: Optional[str] = Field(None, description="ISIN identifier")
    sector: Optional[str] = Field(None, description="Economic sector")
    type: str = Field(..., description="Instrument type")
    lot_size: Optional[int] = Field(None, description="Exchange lot size")
    currency: Optional[str] = Field(None, description="Trading currency")


class PriceData(BaseModel):
    date: str = Field(..., description="Date (ISO format)")
    open: Optional[float] = Field(None, description="Opening price")
    high: Optional[float] = Field(None, description="Highest price")
    low: Optional[float] = Field(None, description="Lowest price")
    close: Optional[float] = Field(None, description="Closing price")
    volume: Optional[float] = Field(None, description="Trading volume")


class IndicatorData(BaseModel):
    date: str = Field(..., description="Date (ISO format)")
    rsi: Optional[float] = Field(None, description="Relative Strength Index")
    macd_line: Optional[float] = Field(None, description="MACD line")
    macd_signal: Optional[float] = Field(None, description="MACD signal line")
    macd_hist: Optional[float] = Field(None, description="MACD histogram")
    sma_20: Optional[float] = Field(None, description="20-day SMA")
    sma_50: Optional[float] = Field(None, description="50-day SMA")
    sma_200: Optional[float] = Field(None, description="200-day SMA")
    bb_upper: Optional[float] = Field(None, description="Upper Bollinger Band")
    bb_lower: Optional[float] = Field(None, description="Lower Bollinger Band")
    bb_mid: Optional[float] = Field(None, description="Middle Bollinger Band")
    volume_sma_20: Optional[float] = Field(None, description="20-day avg volume")
    atr: Optional[float] = Field(None, description="Average True Range")


class EntryZone(BaseModel):
    low: float = Field(..., description="Entry zone lower bound")
    high: float = Field(..., description="Entry zone upper bound")
    current: float = Field(..., description="Current price relative to zone")


class TargetItem(BaseModel):
    level: float = Field(..., description="Target price level")
    type: str = Field(..., description="Target type")
    return_pct: float = Field(..., description="Expected return %")
    rr: float = Field(..., description="Risk-reward ratio")


class TradePlanResponse(BaseModel):
    ticker: str = Field(..., description="Instrument ticker")
    profile: str = Field(..., description="Risk profile used")
    current_price: float = Field(..., description="Current market price")
    entry_zone: EntryZone = Field(..., description="Recommended entry range")
    targets: list[TargetItem] = Field(..., description="Price targets")
    stop_loss: float = Field(..., description="Stop-loss level")
    trailing_after: float = Field(..., description="Trailing stop activation level")
    risk_reward: float = Field(..., description="Overall risk-reward ratio")


class AdviceResponse(BaseModel):
    signal: dict[str, Any] = Field(..., description="Signal data")
    advice: str = Field(..., description="Natural language advice")
    user_id: Optional[int] = Field(None, description="Requesting user ID")


class AskResponse(BaseModel):
    answer: str = Field(..., description="AI-generated answer")
    user_id: Optional[int] = Field(None, description="Requesting user ID")
    risk_profile: str = Field(..., description="User risk profile")


class NewsItem(BaseModel):
    id: int = Field(..., description="News identifier")
    title: Optional[str] = Field(None, description="Article headline")
    summary: str = Field(..., description="Article summary")
    source: Optional[str] = Field(None, description="Source name")
    url: Optional[str] = Field(None, description="Original article URL")
    published_at: Optional[str] = Field(None, description="Publication date")


class GeoRiskItem(BaseModel):
    date: str = Field(..., description="Date")
    score: float = Field(..., description="Aggregate risk score (0-1)")
    components: Optional[dict[str, Any]] = Field(None, description="Risk sub-scores")


class PriceTargetAlert(BaseModel):
    ticker: str = Field(..., description="Instrument ticker")
    current_price: float = Field(..., description="Current price")
    target_price: float = Field(..., description="Target price hit")
    target_type: str = Field(..., description="Target type")
    triggered_pct: float = Field(..., description="Deviation from target")


class DivergenceAlert(BaseModel):
    ticker: str = Field(..., description="Instrument ticker")
    divergence_type: str = Field(..., description="Divergence type")
    indicator: str = Field(..., description="Indicator with divergence")
    strength: float = Field(..., description="Divergence strength (0-1)")


class RebalanceAlert(BaseModel):
    ticker: str = Field(..., description="Instrument ticker")
    current_pct: float = Field(..., description="Current portfolio weight")
    target_pct: float = Field(..., description="Target portfolio weight")
    deviation_pct: float = Field(..., description="Deviation from target")
    reason: str = Field(..., description="Rebalance reason")


class ScenarioItem(BaseModel):
    name: str = Field(..., description="Scenario name")
    loss_pct: float = Field(..., description="Portfolio loss %")
    loss: float = Field(..., description="Absolute loss")
    total_after: float = Field(..., description="Portfolio value after shock")
    var_95: float | None = Field(None, description="Value at Risk (95%)")


class MonteCarloItem(BaseModel):
    var_95: float = Field(..., description="Value at Risk (95%)")
    cvar_95: float = Field(..., description="Conditional VaR (95%)")
    var_99: float = Field(..., description="Value at Risk (99%)")
    mean_return: float = Field(..., description="Expected return")


class ScenarioResponse(BaseModel):
    total: float = Field(..., description="Current portfolio value")
    positions: list[dict[str, Any]] = Field(..., description="Position breakdown")
    scenarios: list[ScenarioItem] = Field(..., description="Scenario results")
    monte_carlo: MonteCarloItem | None = Field(None, description="Monte Carlo results")
    bootstrap: MonteCarloItem | None = Field(None, description="Bootstrap results")
    sector_breakdown: dict[str, float] = Field(..., description="Sector allocation")


class AlertItem(BaseModel):
    news_id: int = Field(..., description="News article ID")
    ticker: str = Field(..., description="Related ticker")
    title: str = Field(..., description="Alert title")
    category: str = Field(..., description="Alert category")
    subcategory: str = Field(..., description="Alert subcategory")
    source_name: str = Field(..., description="Source name")
    published_at: str = Field(..., description="Publication date")
    priority: str = Field(..., description="Priority level")
    priority_score: float = Field(..., description="Priority score (0-1)")
    anomaly_score: float = Field(..., description="Anomaly detection score")
    predicted_return: float = Field(..., description="Predicted return impact")
    impact_confidence: float = Field(..., description="Prediction confidence")
    in_portfolio: bool = Field(..., description="In portfolio flag")
    reason: str = Field(..., description="Alert rationale")


class AlertResponse(BaseModel):
    alerts: list[AlertItem] = Field(..., description="Active alerts")


class FeatureImportance(BaseModel):
    feature: str = Field(..., description="Feature name")
    importance: float = Field(..., description="Importance score")


class ImpactAttributionResponse(BaseModel):
    news_id: int = Field(..., description="News article ID")
    ticker: str = Field(..., description="Affected ticker")
    feature_importances: list[FeatureImportance] = Field(..., description="Top features")


class AlertPreferencesResponse(BaseModel):
    min_severity: str = Field(..., description="Minimum alert severity (LOW, MEDIUM, HIGH, CRITICAL)")
    muted_tickers: list[str] = Field(..., description="List of muted tickers")
    quiet_hours_start: str | None = Field(None, description="Quiet hours start time (HH:MM)")
    quiet_hours_end: str | None = Field(None, description="Quiet hours end time (HH:MM)")


# ── Bond endpoints ─────────────────────────────────────────────────────

class BondDetailResponse(BaseModel):
    issuer: str = Field(..., description="Issuer name")
    isin: str = Field(..., description="ISIN identifier")
    ticker: str = Field(..., description="Ticker symbol")
    currency: str = Field("RUB", description="Trading currency")
    nominal: float = Field(..., description="Face value")
    couponRate: float = Field(..., description="Coupon rate % per annum")
    issueDate: str | None = Field(None, description="Issue date")
    maturityDate: str | None = Field(None, description="Maturity date")
    offerDate: str | None = Field(None, description="Put option date")
    amortization: bool = Field(False, description="Has amortization")


class BondAnalysisResponse(BaseModel):
    score: float = Field(..., description="AI score 0-100")
    verdict: str = Field(..., description="Strong buy / buy / hold / reduce / sell")
    pros: list[str] = Field(default_factory=list, description="Positive factors")
    cons: list[str] = Field(default_factory=list, description="Negative factors")
    risks: list[str] = Field(default_factory=list, description="Risk factors")
    allocation: float = Field(..., description="Recommended allocation %")
    updatedAt: str = Field(..., description="Last updated ISO timestamp")


class BondAIAnalysisResponse(BaseModel):
    summary: str = Field(..., description="AI summary")
    strengths: list[str] = Field(default_factory=list, description="Strengths")
    weaknesses: list[str] = Field(default_factory=list, description="Weaknesses")
    risks: list[str] = Field(default_factory=list, description="Risks")
    recommendation: str = Field(..., description="Buy / Hold / Sell")
    investmentHorizon: str = Field(..., description="Recommended horizon")
    confidence: float = Field(..., description="AI confidence 0-100")


class BondMetricsResponse(BaseModel):
    yieldToMaturity: float | None = Field(None, description="YTM %")
    currentYield: float | None = Field(None, description="Current yield %")
    duration: float | None = Field(None, description="Macaulay duration years")
    modifiedDuration: float | None = Field(None, description="Modified duration years")
    convexity: float | None = Field(None, description="Convexity")
    coupon: float | None = Field(None, description="Coupon value in RUB")
    accruedInterest: float | None = Field(None, description="Accrued interest (НКД) in RUB")
    purchasePrice: float | None = Field(None, description="Average purchase price in RUB")
    marketPrice: float | None = Field(None, description="Current market price in RUB")
    profit: float | None = Field(None, description="Profit / loss in RUB")
    fairValue: float | None = Field(None, description="Estimated fair value in RUB")


class CouponPaymentResponse(BaseModel):
    id: str = Field(..., description="Coupon ID")
    date: str = Field(..., description="Payment date")
    amount: float = Field(..., description="Payment amount in RUB")
    status: str = Field(..., description="paid / pending / forecast")


class CashFlowItemResponse(BaseModel):
    id: str = Field(..., description="Cash flow item ID")
    date: str = Field(..., description="Event date")
    amount: float = Field(..., description="Amount in RUB")
    type: str = Field(..., description="coupon / redemption")
    status: str = Field(..., description="paid / expected / forecast")


class CashFlowSummaryResponse(BaseModel):
    totalPayments: int = Field(..., description="Total number of payments")
    remainingCoupons: int = Field(..., description="Remaining coupon payments")
    totalCashFlow: float = Field(..., description="Total projected cash flow")
    averageCoupon: float = Field(..., description="Average coupon amount")
    maturityDate: str = Field(..., description="Maturity date")


class BondCashFlowResponse(BaseModel):
    items: list[CashFlowItemResponse] = Field(..., description="Cash flow items")
    summary: CashFlowSummaryResponse = Field(..., description="Cash flow summary")


class BondPriceHistoryResponse(BaseModel):
    price: list[dict[str, Any]] = Field(..., description="Price points [{time, value}]")
    volume: list[dict[str, Any]] = Field(..., description="Volume points [{time, value}]")
