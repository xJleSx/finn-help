from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.db.connection import get_session
from src.db.models import (
    ComplianceEvent,
    MarginAccount,
    Order,
    ShortPosition,
    User,
)
from src.interfaces.api.auth import decode_token, require_user
from src.interfaces.api.rbac.audit import AuditTrail
from src.trading.execution.engine import execute_compliance_check, execute_order
from src.trading.margin import (
    compute_leverage_info,
)
from src.trading.tax.reporter import (
    generate_3ndfl_section,
    generate_broker_report_csv,
    generate_tax_report,
    load_dividends_from_db,
    load_trades_from_db,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/trading/v2", tags=["trading_v2"])


def _get_user_id(request: Request) -> int:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 7:
        try:
            payload = decode_token(auth[7:])
            return int(payload.get("sub", 0))
        except Exception:
            pass
    return 0


class OrderRequest(BaseModel):
    ticker: str = Field(..., description="Instrument ticker")
    direction: str = Field(..., description="BUY / SELL / SHORT / COVER")
    quantity: int = Field(..., ge=1, description="Number of shares")
    price: Optional[float] = Field(None, description="Limit price")
    order_type: str = Field("market", description="market / limit / ioc / fok")
    time_in_force: str = Field("day", description="day / ioc / fok / gtc")
    is_short: bool = Field(False, description="Short sell flag")
    reason: str = Field("", description="Order reason")


class OrderResponse(BaseModel):
    status: str
    order_id: Optional[str] = None
    db_id: Optional[int] = None
    ticker: str
    direction: str
    quantity: int
    price: float
    order_type: str
    time_in_force: str
    is_short: bool
    filled_quantity: int = 0
    remaining_quantity: int = 0
    checks: Optional[list[dict[str, Any]]] = None
    warnings: Optional[list[str]] = None


class MarginResponse(BaseModel):
    portfolio_value: float
    total_loan: float
    leverage_ratio: float
    margin_call_level: float
    liquidation_level: float
    free_margin: float
    used_margin: float
    margin_status: str


class ComplianceCheckResponse(BaseModel):
    passed: bool
    checks: list[dict[str, Any]]
    warnings: list[str]
    blocks: list[str]


class TaxReportResponse(BaseModel):
    year: int
    total_realised_pnl: float
    total_dividends: float
    total_tax_due: float
    n_lots: int
    n_dividends: int
    broker_commission_total: float
    csv_report: Optional[str] = None
    ndfl_section: Optional[dict[str, Any]] = None


class ShortPositionResponse(BaseModel):
    ticker: str
    quantity: int
    avg_price: float
    margin_held: float
    borrow_rate: float
    opened_at: str


class ComplianceEventResponse(BaseModel):
    id: int
    event_type: str
    ticker: Optional[str]
    severity: str
    details: Optional[str]
    created_at: str


@router.post("/order", response_model=OrderResponse)
async def place_order(req: OrderRequest, request: Request, user: User = Depends(require_user)):
    try:
        result = await execute_order(
            ticker=req.ticker.upper(),
            direction=req.direction.upper(),
            quantity=req.quantity,
            price=req.price,
            reason=req.reason,
            order_type=req.order_type.lower(),
            time_in_force=req.time_in_force.lower(),
            is_short=req.is_short,
        )
        ip = request.client.host if request.client else "unknown"
        AuditTrail.log(
            user_id=str(user.id),
            action="execute_order",
            resource=f"order:{result.ticker}",
            details=f"direction={result.direction} quantity={result.quantity} status={result.status}",
            ip_address=ip,
            success=result.status.lower() in ("filled", "simulated", "pending"),
        )
        return OrderResponse(
            status=result.status,
            order_id=result.order_id,
            db_id=result.db_id or None,
            ticker=result.ticker,
            direction=result.direction,
            quantity=result.quantity,
            price=result.price,
            order_type=result.order_type,
            time_in_force=result.time_in_force,
            is_short=result.is_short,
            filled_quantity=result.filled_quantity,
            remaining_quantity=result.remaining_quantity,
        )
    except Exception:
        logger.exception("trading_v2.order_failed", ticker=req.ticker, direction=req.direction)
        raise


@router.post("/compliance/check", response_model=ComplianceCheckResponse)
async def run_compliance_check(
    ticker: str = Query(..., description="Instrument ticker"),
    direction: str = Query("BUY", description="BUY/SELL/SHORT/COVER"),
    quantity: int = Query(1, ge=1),
    price: float = Query(0.0, ge=0),
    is_short: bool = Query(False),
    portfolio_value: float = Query(1_000_000),
):
    try:
        result = await execute_compliance_check(
            ticker=ticker.upper(),
            direction=direction.upper(),
            quantity=quantity,
            price=price,
            portfolio_value=portfolio_value,
            is_short=is_short,
        )
        return ComplianceCheckResponse(
            passed=result["passed"],
            checks=result["checks"],
            warnings=result["warnings"],
            blocks=result["blocks"],
        )
    except Exception:
        logger.exception("trading_v2.compliance_check_failed", ticker=ticker, direction=direction)
        raise


@router.get("/margin", response_model=MarginResponse)
async def get_margin_info(user: User = Depends(require_user)):
    db = get_session()
    try:
        margin = db.query(MarginAccount).filter_by(user_id=user.id).first()
        if not margin:
            return MarginResponse(
                portfolio_value=0,
                total_loan=0,
                leverage_ratio=1.0,
                margin_call_level=0,
                liquidation_level=0,
                free_margin=0,
                used_margin=0,
                margin_status="safe",
            )
        info = compute_leverage_info(
            portfolio_value=0,
            total_loan=margin.total_loan or 0,
            cash_balance=0,
            margin_used=margin.margin_used or 0,
        )
        return MarginResponse(
            portfolio_value=info.portfolio_value,
            total_loan=info.total_loan,
            leverage_ratio=info.leverage_ratio,
            margin_call_level=info.margin_call_level,
            liquidation_level=info.liquidation_level,
            free_margin=info.free_margin,
            used_margin=info.used_margin,
            margin_status=info.margin_status,
        )
    except Exception:
        logger.exception("trading_v2.margin_failed", user_id=user.id)
        raise
    finally:
        db.close()


@router.get("/short-positions", response_model=list[ShortPositionResponse])
async def get_short_positions(user: User = Depends(require_user)):
    db = get_session()
    try:
        positions = db.query(ShortPosition).filter_by(user_id=user.id).all()
        return [
            ShortPositionResponse(
                ticker=p.ticker,
                quantity=p.quantity,
                avg_price=p.avg_price or 0,
                margin_held=p.margin_held or 0,
                borrow_rate=p.borrow_rate or 0,
                opened_at=p.opened_at.isoformat() if p.opened_at else "",
            )
            for p in positions
        ]
    finally:
        db.close()


@router.get("/orders", response_model=list[dict[str, Any]])
async def get_orders(
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
):
    db = get_session()
    try:
        query = db.query(Order).order_by(Order.created_at.desc())
        if status:
            query = query.filter(Order.status == status)
        if ticker:
            query = query.filter(Order.ticker == ticker.upper())
        orders = query.limit(limit).all()
        return [
            {
                "id": o.id,
                "ticker": o.ticker,
                "direction": o.direction,
                "quantity": o.quantity,
                "price": o.price,
                "order_type": o.order_type,
                "time_in_force": o.time_in_force,
                "status": o.status,
                "filled_quantity": o.filled_quantity,
                "remaining_quantity": o.remaining_quantity,
                "is_short": o.is_short,
                "commission": o.commission,
                "executed_price": o.executed_price,
                "created_at": o.created_at.isoformat() if o.created_at else "",
            }
            for o in orders
        ]
    finally:
        db.close()


@router.get("/tax-report", response_model=TaxReportResponse)
async def get_tax_report(
    year: int = Query(2026, ge=2020, le=2030),
    ticker: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
):
    try:
        trades = load_trades_from_db(year=year, ticker=ticker)
        dividends = load_dividends_from_db(year=year, ticker=ticker)
        report = generate_tax_report(year=year, trades=trades, dividends=dividends)
        csv_report = None
        ndfl = None
        if format == "csv":
            csv_report = generate_broker_report_csv(report)
        if format == "ndfl":
            ndfl = generate_3ndfl_section(report)
        return TaxReportResponse(
            year=report.year,
            total_realised_pnl=report.total_realised_pnl,
            total_dividends=report.total_dividends,
            total_tax_due=report.total_tax_due,
            n_lots=len(report.lots),
            n_dividends=len(report.dividends),
            broker_commission_total=report.broker_commission_total,
            csv_report=csv_report,
            ndfl_section=ndfl,
        )
    except Exception:
        logger.exception("trading_v2.tax_report_failed", year=year, ticker=ticker)
        raise


@router.get("/compliance/events", response_model=list[ComplianceEventResponse])
async def get_compliance_events(
    limit: int = Query(50, ge=1, le=500),
    severity: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
):
    db = get_session()
    try:
        query = db.query(ComplianceEvent).order_by(ComplianceEvent.created_at.desc())
        if severity:
            query = query.filter(ComplianceEvent.severity == severity)
        if event_type:
            query = query.filter(ComplianceEvent.event_type == event_type)
        events = query.limit(limit).all()
        return [
            ComplianceEventResponse(
                id=e.id,
                event_type=e.event_type,
                ticker=e.ticker,
                severity=e.severity,
                details=e.details,
                created_at=e.created_at.isoformat() if e.created_at else "",
            )
            for e in events
        ]
    finally:
        db.close()


@router.post("/order/cancel")
async def cancel_order(order_id: int, request: Request, user: User = Depends(require_user)):
    db = get_session()
    try:
        order = db.query(Order).filter_by(id=order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        order.status = "cancelled"
        db.commit()
        ip = request.client.host if request.client else "unknown"
        AuditTrail.log(
            user_id=str(user.id),
            action="cancel_order",
            resource=f"order:{order_id}",
            details=f"ticker={order.ticker} direction={order.direction}",
            ip_address=ip,
            success=True,
        )
        return {"status": "cancelled", "order_id": order_id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("trading_v2.cancel_order_failed", order_id=order_id)
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/brokers", response_model=list[dict[str, str]])
async def list_brokers():
    from src.constants import BROKER_NAMES
    from src.trading.brokers.registry import get_default_broker, list_brokers

    brokers = []
    for name in list_brokers():
        brokers.append(
            {
                "name": name,
                "label": BROKER_NAMES.get(name, name),
                "is_default": name == get_default_broker(),
            }
        )
    return brokers
