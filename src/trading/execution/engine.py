import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional, cast

from src.config import personal, settings
from src.core.context import (
    generate_id,
    get_request_id,
    set_request_id,
)
from src.core.credential_store import get_broker_token as _get_broker_token_db
from src.core.resilience import CircuitBreakerOpenError, get_circuit_breaker
from src.db.connection import session_scope
from src.trading.brokers.registry import create_broker_client, get_default_broker
from src.trading.compliance.aml import check_order_aml
from src.trading.compliance.limits import (
    check_position_limit,
    check_short_eligibility,
)
from src.trading.execution.audit import log_trade, save_order
from src.trading.execution.stoploss import position_tracker
from src.trading.types import (
    Direction,
    TradeMode,
)

logger = logging.getLogger(__name__)

_BROKER_TOKEN_ATTRS: dict[str, str] = {
    "tbank": "tinkoff_token",
    "bcs": "bcs_refresh_token",
}


def _get_broker_token(broker_name: str, user_id: int = 0) -> str:
    try:
        with session_scope() as db:
            token = _get_broker_token_db(user_id, broker_name, db)
            if token:
                return token
    except Exception as e:
        logger.debug("DB broker token lookup failed, falling back to env: %s", e)
    attr = _BROKER_TOKEN_ATTRS.get(broker_name.lower())
    if attr and hasattr(settings, attr):
        return str(getattr(settings, attr) or "")
    return ""


async def _notify_trade(record: "OrderRecord", reason: str = "") -> None:
    try:
        from src.interfaces.telegram_broadcaster import broadcast_trade

        await broadcast_trade(
            ticker=record.ticker,
            direction=record.direction,
            quantity=record.quantity,
            price=record.price,
            status=record.status,
            reason=reason,
            order_id=record.order_id or "",
        )
    except Exception as exc:
        logger.exception("Failed to schedule trade broadcast: %s", exc)


class OrderRecord:
    def __init__(
        self,
        ticker: str,
        direction: str,
        quantity: int,
        price: float,
        mode: TradeMode,
        reason: str = "",
        order_type: str = "market",
        time_in_force: str = "day",
        is_short: bool = False,
    ):
        self.ticker = ticker
        self.direction = direction
        self.quantity = quantity
        self.price = price
        self.mode = mode
        self.reason = reason
        self.order_type = order_type
        self.time_in_force = time_in_force
        self.is_short = is_short
        self.created_at = datetime.now(timezone.utc)
        self.order_id: Optional[str] = None
        self.status = "pending"
        self.db_id: int = 0
        self.request_id: str = get_request_id() or generate_id("req", 12)
        self.idempotency_key: str = generate_id("idem", 24)
        self.filled_quantity: int = 0
        self.remaining_quantity: int = quantity
        self.executed_price: Optional[float] = None
        self.commission: float = 0.0
        self.fills: list[dict[str, Any]] = []


_execution_log: "deque[OrderRecord]" = deque(maxlen=1000)
_log_loaded: bool = False
_mode_lock = asyncio.Lock()
_mode = TradeMode.DRY_RUN


def reload_execution_log() -> None:
    """Load pending orders from DB into in-memory log after restart."""
    global _log_loaded
    if _log_loaded:
        return
    from src.db.connection import get_session as _get_db
    from src.db.models import Order as _OrdModel

    db = _get_db()
    try:
        pending = (
            db.query(_OrdModel)
            .filter(_OrdModel.status.in_(["pending", "pending_approval", "submitted", "partial"]))
            .order_by(_OrdModel.created_at.desc())
            .limit(1000)
            .all()
        )
        for o in pending:
            rec = OrderRecord(
                ticker=o.ticker,
                direction=o.direction,
                quantity=o.quantity,
                price=o.price or 0.0,
                mode=TradeMode(o.mode) if hasattr(TradeMode, o.mode.upper()) else TradeMode.MANUAL,
                reason=o.reason or "",
                order_type=o.order_type or "market",
                time_in_force=o.time_in_force or "day",
                is_short=o.is_short or False,
            )
            rec.created_at = o.created_at
            rec.order_id = o.order_id_ext
            rec.status = o.status
            rec.db_id = o.id
            rec.filled_quantity = o.filled_quantity or 0
            rec.remaining_quantity = o.remaining_quantity or o.quantity
            rec.executed_price = o.executed_price
            rec.commission = o.commission or 0.0
            _execution_log.append(rec)
        _log_loaded = True
        if pending:
            logger.info("Loaded %d pending orders from DB into execution log", len(pending))
    except Exception:
        logger.exception("Unhandled exception")
        logger.exception("Failed to load pending orders from DB")
    finally:
        db.close()


async def set_mode(mode: TradeMode) -> None:
    global _mode
    async with _mode_lock:
        _mode = mode
        logger.info("Trade mode set to %s", mode.value)


def get_mode() -> TradeMode:
    return _mode


def get_log(limit: int = 20) -> list[dict[str, object]]:
    reload_execution_log()
    entries = list(_execution_log)[-limit:]
    return [
        {
            "ticker": r.ticker,
            "direction": r.direction,
            "quantity": r.quantity,
            "price": r.price,
            "mode": r.mode.value,
            "reason": r.reason,
            "status": r.status,
            "order_type": r.order_type,
            "time_in_force": r.time_in_force,
            "is_short": r.is_short,
            "order_id": r.order_id,
            "filled_quantity": r.filled_quantity,
            "remaining_quantity": r.remaining_quantity,
            "time": r.created_at.isoformat(),
            "request_id": r.request_id,
            "idempotency_key": r.idempotency_key,
        }
        for r in entries
    ]


async def execute_order(
    ticker: str,
    direction: str,
    quantity: int,
    price: Optional[float] = None,
    figi: Optional[str] = None,
    reason: str = "",
    mode_override: Optional[TradeMode] = None,
    order_type: str = "market",
    time_in_force: str = "day",
    is_short: bool = False,
    skip_risk_checks: bool = False,
    broker_name: Optional[str] = None,
) -> OrderRecord:
    global _mode
    effective_mode = mode_override if mode_override is not None else _mode

    rid = get_request_id()
    if not rid:
        set_request_id(generate_id("req", 12))

    record = OrderRecord(
        ticker=ticker,
        direction=direction,
        quantity=quantity,
        price=price or 0.0,
        mode=effective_mode,
        reason=reason,
        order_type=order_type,
        time_in_force=time_in_force,
        is_short=is_short,
    )

    effective_direction = Direction.COVER if (is_short and direction.upper() == "BUY") else Direction.SHORT if is_short else Direction(direction.upper())

    if not skip_risk_checks and effective_mode != TradeMode.DRY_RUN:
        from src.db.connection import get_session as _risk_db
        from src.db.models import Portfolio as _PortModel

        portfolio_value: float = 0.0
        _rdb = _risk_db()
        try:
            port = _rdb.query(_PortModel).first()
            if port:
                portfolio_value = float(port.total_value or 0)
        except Exception as e:
            logger.debug("Could not get portfolio value for risk check: %s", e)
        finally:
            _rdb.close()

        from src.trading.risk.manager import get_risk_manager

        rm = get_risk_manager()
        ok, risk_msg = await rm.can_trade(
            ticker=ticker,
            quantity=quantity,
            price=record.price,
            portfolio_value=portfolio_value,
            direction=direction,
            is_short=is_short,
        )
        if not ok:
            record.status = "rejected"
            record.reason = f"RISK: {risk_msg}"
            logger.warning("Order REJECTED: %s %d %s — %s", direction, quantity, ticker, risk_msg)
            _execution_log.append(record)
            record.db_id = save_order(record)
            await _notify_trade(record, reason)
            return record

    if effective_mode == TradeMode.DRY_RUN:
        record.status = "simulated"
        record.order_id = f"dry_{datetime.now(timezone.utc).timestamp()}"
        logger.info(
            "DRY-RUN %s %d %s at %.2f (%s) type=%s tif=%s",
            direction,
            quantity,
            ticker,
            record.price,
            reason,
            order_type,
            time_in_force,
        )
        if effective_direction == Direction.COVER:
            position_tracker.cover_short(ticker, quantity, record.price)
        elif effective_direction == Direction.BUY:
            position_tracker.update(ticker, "BUY", quantity, record.price)
        elif effective_direction in (Direction.SELL, Direction.SHORT):
            position_tracker.update(ticker, "SELL", quantity, record.price)
            if is_short:
                position_tracker.add_short(ticker, quantity, record.price)
        _execution_log.append(record)
        record.db_id = save_order(record)
        await _notify_trade(record, reason)
        return record

    if effective_mode == TradeMode.AUTO:
        if not settings.enable_trading:
            record.status = "failed"
            logger.error("Trading disabled — set ENABLE_TRADING=true to use AUTO mode")
            _execution_log.append(record)
            record.db_id = save_order(record)
            await _notify_trade(record, reason)
            return record
        broker = broker_name or get_default_broker()
        broker_token = _get_broker_token(broker)
        if not broker_token:
            record.status = "failed"
            logger.error("No token configured for broker '%s' — cannot execute AUTO mode order", broker)
            _execution_log.append(record)
            record.db_id = save_order(record)
            await _notify_trade(record, reason)
            return record

        executed_shares = 0
        slippage = 0.0
        try:
            from src.db.connection import get_session as _get_db
            from src.db.models import Instrument as _InstModel

            resolved_figi = figi
            lot_size = 1
            _db = _get_db()
            try:
                inst = _db.query(_InstModel).filter_by(ticker=ticker).first()
                if inst:
                    if not resolved_figi and inst.figi:
                        resolved_figi = str(inst.figi)
                    lot_size = int(inst.lot_size or 1)
            finally:
                _db.close()

            if not resolved_figi:
                record.status = "failed"
                logger.warning("No FIGI found for %s, cannot place order", ticker)
                _execution_log.append(record)
                record.db_id = save_order(record)
                await _notify_trade(record, reason)
                return record

            quantity_lots = quantity // lot_size
            if quantity_lots < 1:
                record.status = "failed"
                logger.warning("Quantity %d is less than one lot (%d) for %s", quantity, lot_size, ticker)
                _execution_log.append(record)
                record.db_id = save_order(record)
                await _notify_trade(record, reason)
                return record

            exec_cfg = personal.get("execution", {})
            delay = cast("dict[str, Any]", exec_cfg).get("delay_ms", 500) if isinstance(exec_cfg, dict) else 500
            if delay > 0:
                await asyncio.sleep(delay / 1000)

            requested_price = record.price

            cb_name = f"{broker}_orders"
            orders_cb = get_circuit_breaker(cb_name)
            if orders_cb.is_open:
                logger.warning(
                    "%s circuit breaker OPEN — falling back to DRY_RUN for %s %s",
                    cb_name,
                    direction,
                    ticker,
                )
                record.status = "simulated"
                record.order_id = f"dry_cb_{datetime.now(timezone.utc).timestamp()}"
                if effective_direction == Direction.COVER:
                    position_tracker.cover_short(ticker, quantity, record.price)
                elif effective_direction == Direction.BUY:
                    position_tracker.update(ticker, "BUY", quantity, record.price)
                elif effective_direction in (Direction.SELL, Direction.SHORT):
                    position_tracker.update(ticker, "SELL", quantity, record.price)
                    if is_short:
                        position_tracker.add_short(ticker, quantity, record.price)
                _execution_log.append(record)
                record.db_id = save_order(record)
                await _notify_trade(record, reason=f"CB_OPEN_FALLBACK {reason}")
                return record

            async with create_broker_client(broker) as client:
                accounts = await client.get_accounts()
                if not accounts:
                    record.status = "failed"
                    logger.warning("No accounts found for broker %s", broker)
                    _execution_log.append(record)
                    record.db_id = save_order(record)
                    await _notify_trade(record, reason)
                    return record

                account_id = accounts[0].id if hasattr(accounts[0], "id") else str(accounts[0].get("id", ""))

                try:
                    mapped_direction = (
                        "COVER" if is_short and direction.upper() == "BUY" else "SHORT" if is_short and direction.upper() == "SELL" else direction
                    )
                    result = await client.place_order(
                        figi=resolved_figi,
                        quantity=quantity_lots,
                        direction=mapped_direction,
                        account_id=account_id,
                        idempotency_key=record.idempotency_key,
                    )
                except CircuitBreakerOpenError:
                    logger.warning(
                        "Circuit breaker OPEN during place_order for %s — falling back to DRY_RUN",
                        ticker,
                    )
                    record.status = "simulated"
                    record.order_id = f"dry_cb_{datetime.now(timezone.utc).timestamp()}"
                    if effective_direction == Direction.COVER:
                        position_tracker.cover_short(ticker, quantity, record.price)
                    elif effective_direction == Direction.BUY:
                        position_tracker.update(ticker, "BUY", quantity, record.price)
                    elif effective_direction in (Direction.SELL, Direction.SHORT):
                        position_tracker.update(ticker, "SELL", quantity, record.price)
                        if is_short:
                            position_tracker.add_short(ticker, quantity, record.price)
                    _execution_log.append(record)
                    record.db_id = save_order(record)
                    await _notify_trade(record, reason=f"CB_OPEN_FALLBACK {reason}")
                    return record

                _order_id = result.order_id or result.get("order_id")
                record.order_id = str(_order_id) if _order_id is not None else None
                record.status = str(result.status or result.get("status", "unknown"))
                executed_lots = int(result.executed_quantity or result.get("executed_quantity", 0))
                executed_shares = executed_lots * lot_size
                executed_price = result.executed_price or result.get("executed_price")
                if executed_price is not None:
                    record.price = cast(float, executed_price)
                    record.executed_price = record.price
                record.filled_quantity = executed_shares
                record.remaining_quantity = max(0, quantity - executed_shares)

                slippage = 0.0
                if requested_price and requested_price > 0 and executed_price is not None:
                    slippage = abs(cast(float, executed_price) - requested_price) / requested_price
                logger.info(
                    "ORDER RESULT: %s %d lots (%d shares) %s at %.2f (id=%s) status=%s filled=%d",
                    direction,
                    executed_lots,
                    executed_shares,
                    ticker,
                    record.price,
                    record.order_id,
                    record.status,
                    record.filled_quantity,
                )

                if record.status in ("filled", "partial") and executed_shares > 0:
                    if is_short:
                        position_tracker.add_short(ticker, executed_shares, record.price)
                    else:
                        position_tracker.update(ticker, direction, executed_shares, record.price)

                    sl_pct = cast(float, personal.get("stop_loss_pct", 0.05))
                    tp_pct = cast(float, personal.get("take_profit_pct", 0.10))
                    _sl_db = _get_db()
                    try:
                        from src.db.models import Indicator as _IndicatorModel

                        latest = (
                            _sl_db.query(_IndicatorModel)
                            .filter_by(instrument_id=(inst.id if inst else 0))
                            .order_by(_IndicatorModel.date.desc())
                            .first()
                        )
                        if latest and latest.atr and float(latest.atr) > 0 and record.price > 0:
                            from src.trading.risk.manager import compute_stop_loss as _compute_sl

                            atr_result = _compute_sl(record.price, float(latest.atr), multiplier=2.0)
                            if atr_result and atr_result.get("stop_loss_pct"):
                                sl_pct = abs(atr_result["stop_loss_pct"]) / 100
                    except Exception as e:
                        logger.warning("Failed to compute stop loss for %s: %s", ticker, e)
                    finally:
                        _sl_db.close()
                    rr_ratio = cast(float, personal.get("rr_ratio", 2.0))
                    tp_pct = max(tp_pct, sl_pct * rr_ratio)
                    position_tracker.set_sl_tp(ticker, sl_pct=sl_pct, tp_pct=tp_pct)

                if record.status in ("filled", "partial"):
                    from src.db.connection import get_session as _upd_db
                    from src.db.models import Order as _OrdModel

                    _upd = _upd_db()
                    try:
                        o = _upd.query(_OrdModel).filter_by(id=record.db_id).first()
                        if o:
                            o.filled_quantity = record.filled_quantity
                            o.remaining_quantity = record.remaining_quantity
                            o.is_short = is_short
                            _upd.commit()
                    except Exception:
                        logger.warning("Failed to update order %s in DB", record.db_id, exc_info=True)
                    finally:
                        _upd.close()

        except Exception as exc:
            if record.status not in ("filled", "partial"):
                record.status = "failed"
            logger.error("Order failed: %s %d %s: %s", direction, quantity, ticker, exc, exc_info=True)

        _execution_log.append(record)
        record.db_id = save_order(record)
        if slippage > 0 and executed_shares > 0:
            log_trade(
                ticker=ticker,
                direction=direction,
                quantity=executed_shares,
                price=record.price,
                slippage=slippage,
                reason=record.reason,
                order_id=record.db_id or record.order_id or record.idempotency_key,
            )
        await _notify_trade(record, reason)
        return record

    if effective_mode == TradeMode.MANUAL:
        record.status = "pending_approval"
        _execution_log.append(record)
        record.db_id = save_order(record)
        logger.info("MANUAL: %s %d %s at %.2f — awaiting approval", direction, quantity, ticker, record.price)
        return record

    _execution_log.append(record)
    record.db_id = save_order(record)
    await _notify_trade(record, reason)
    return record


async def approve_order(ticker: str, direction: str, quantity: int, idempotency_key: str = "") -> Optional[OrderRecord]:
    if not settings.enable_trading:
        logger.warning("Cannot approve order — trading disabled (ENABLE_TRADING=true)")
        return None
    reload_execution_log()
    async with _mode_lock:
        for r in reversed(_execution_log):
            if r.status != "pending_approval":
                continue
            if r.ticker != ticker or r.direction != direction or r.quantity != quantity:
                continue
            if idempotency_key and r.idempotency_key != idempotency_key:
                continue
            return await execute_order(
                ticker=r.ticker,
                direction=r.direction,
                quantity=r.quantity,
                price=r.price,
                reason=r.reason,
                mode_override=TradeMode.AUTO,
                order_type=r.order_type,
                time_in_force=r.time_in_force,
                is_short=r.is_short,
            )
    return None


async def cancel_pending(ticker: str) -> bool:
    reload_execution_log()
    async with _mode_lock:
        for r in _execution_log:
            if r.ticker == ticker and r.status == "pending_approval":
                r.status = "cancelled"
                logger.info("Pending order cancelled: %s", ticker)
                return True
    return False


async def execute_compliance_check(
    ticker: str,
    direction: str,
    quantity: int,
    price: float,
    user_id: int = 0,
    portfolio_value: float = 0.0,
    is_short: bool = False,
    user_risk_profile: str = "balanced",
) -> dict[str, Any]:
    volume = quantity * price
    results: dict[str, Any] = {
        "passed": True,
        "checks": [],
        "warnings": [],
        "blocks": [],
    }

    aml_check = check_order_aml(user_id, ticker, volume, user_risk_profile)
    results["checks"].append({"check": "aml", "passed": aml_check.passed})
    if not aml_check.passed:
        results["passed"] = False
        results["blocks"].extend(aml_check.blocks)
    results["warnings"].extend(aml_check.warnings)

    if is_short:
        short_check = check_short_eligibility(ticker, quantity, price, portfolio_value)
        results["checks"].append({"check": "short_eligibility", "passed": short_check.passed})
        if not short_check.passed:
            results["passed"] = False
            results["blocks"].extend(short_check.blocks)

    pos_check = check_position_limit(ticker, quantity, price, portfolio_value)
    results["checks"].append({"check": "position_limit", "passed": pos_check.passed})
    if not pos_check.passed:
        results["passed"] = False
        results["blocks"].extend(pos_check.blocks)
    results["warnings"].extend(pos_check.warnings)

    return results
