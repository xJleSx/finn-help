import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from src.brokers.tbank import TBankClient
from src.config import personal, settings
from src.execution.audit import log_trade, save_order, update_order_status
from src.execution.stoploss import position_tracker

logger = logging.getLogger(__name__)


class TradeMode(Enum):
    DRY_RUN = "dry_run"
    MANUAL = "manual"
    AUTO = "auto"


class OrderRecord:
    def __init__(
        self,
        ticker: str,
        direction: str,
        quantity: int,
        price: float,
        mode: TradeMode,
        reason: str = "",
    ):
        self.ticker = ticker
        self.direction = direction
        self.quantity = quantity
        self.price = price
        self.mode = mode
        self.reason = reason
        self.created_at = datetime.now(timezone.utc)
        self.order_id: Optional[str] = None
        self.status = "pending"
        self.db_id: int = 0


_execution_log: "deque[OrderRecord]" = deque(maxlen=1000)
_mode_lock = asyncio.Lock()


async def set_mode(mode: TradeMode):
    global _mode
    async with _mode_lock:
        _mode = mode
        logger.info("Trade mode set to %s", mode.value)


def get_mode() -> TradeMode:
    return _mode


def get_log(limit: int = 20) -> list[dict]:
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
            "order_id": r.order_id,
            "time": r.created_at.isoformat(),
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
) -> OrderRecord:
    global _mode

    record = OrderRecord(
        ticker=ticker,
        direction=direction,
        quantity=quantity,
        price=price or 0.0,
        mode=_mode,
        reason=reason,
    )

    if _mode == TradeMode.DRY_RUN:
        record.status = "simulated"
        record.order_id = f"dry_{datetime.now(timezone.utc).timestamp()}"
        logger.info(
            "DRY-RUN %s %d %s at %.2f (%s)",
            direction, quantity, ticker, record.price, reason,
        )
        position_tracker.update(ticker, direction, quantity, record.price)
        _execution_log.append(record)
        record.db_id = save_order(record)
        return record

    if not settings.tinkoff_token and _mode == TradeMode.AUTO:
        record.status = "failed"
        logger.error("No TINKOFF_TOKEN set — cannot execute AUTO mode order")
        _execution_log.append(record)
        record.db_id = save_order(record)
        return record

    if _mode == TradeMode.MANUAL:
        record.status = "pending_approval"
        _execution_log.append(record)
        record.db_id = save_order(record)
        logger.info("MANUAL: %s %d %s at %.2f — awaiting approval", direction, quantity, ticker, record.price)
        return record

    # AUTO mode
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
                    resolved_figi = inst.figi
                lot_size = inst.lot_size or 1
        finally:
            _db.close()

        if not resolved_figi:
            record.status = "failed"
            logger.warning("No FIGI found for %s, cannot place order", ticker)
            _execution_log.append(record)
            record.db_id = save_order(record)
            return record

        quantity_lots = quantity // lot_size
        if quantity_lots < 1:
            record.status = "failed"
            logger.warning("Quantity %d is less than one lot (%d) for %s", quantity, lot_size, ticker)
            _execution_log.append(record)
            record.db_id = save_order(record)
            return record

        delay = (personal.get("execution", {}) or {}).get("delay_ms", 500)
        if delay > 0:
            await asyncio.sleep(delay / 1000)

        use_sandbox = settings.tinkoff_sandbox
        requested_price = record.price
        async with TBankClient(use_sandbox=use_sandbox) as client:
            accounts = await client.get_accounts()
            if not accounts:
                record.status = "failed"
                logger.warning("No accounts found")
                _execution_log.append(record)
                record.db_id = save_order(record)
                return record

            account_id = accounts[0]["id"]

            result = await client.place_order(
                figi=resolved_figi,
                quantity=quantity_lots,
                direction=direction,
                account_id=account_id,
            )
            record.order_id = result.get("order_id")
            record.status = result.get("status", "unknown")
            executed_lots = result.get("executed_quantity", 0)
            executed_shares = executed_lots * lot_size
            executed_price = result.get("executed_price")
            if executed_price is not None:
                record.price = executed_price

            slippage = 0.0
            if requested_price and requested_price > 0 and executed_price is not None:
                slippage = abs(executed_price - requested_price) / requested_price
            logger.info(
                "ORDER FILLED: %s %d lots (%d shares) %s at %.2f (id=%s)",
                direction, executed_lots, executed_shares, ticker, record.price, record.order_id,
            )

            if record.status in ("filled", "partial") and executed_shares > 0:
                position_tracker.update(ticker, direction, executed_shares, record.price)
                sl_pct = personal.get("stop_loss_pct", 0.05)
                tp_pct = personal.get("take_profit_pct", 0.10)
                _sl_db = _get_db()
                try:
                    from src.db.models import Indicator as _IndicatorModel
                    latest = _sl_db.query(_IndicatorModel).filter_by(
                        instrument_id=(inst.id if inst else 0)
                    ).order_by(_IndicatorModel.date.desc()).first()
                    if latest and latest.atr and latest.atr > 0 and record.price > 0:
                        from src.risk.manager import compute_stop_loss as _compute_sl
                        atr_result = _compute_sl(record.price, latest.atr, multiplier=2.0)
                        if atr_result and atr_result["stop_loss_pct"]:
                            sl_pct = abs(atr_result["stop_loss_pct"]) / 100
                except Exception:
                    pass
                finally:
                    _sl_db.close()
                rr_ratio = personal.get("rr_ratio", 2.0)
                tp_pct = max(tp_pct, sl_pct * rr_ratio)
                position_tracker.set_sl_tp(ticker, sl_pct=sl_pct, tp_pct=tp_pct)

            # log slippage
            if slippage > 0 and record.db_id:
                log_trade(
                    ticker=ticker,
                    direction=direction,
                    quantity=executed_shares,
                    price=record.price,
                    slippage=slippage,
                    reason=record.reason,
                    order_id=record.db_id,
                )
    except Exception as e:
        record.status = "failed"
        logger.error("Order failed: %s %d %s: %s", direction, quantity, ticker, e, exc_info=True)

    _execution_log.append(record)
    record.db_id = save_order(record)
    return record


async def approve_order(ticker: str, direction: str, quantity: int) -> Optional[OrderRecord]:
    async with _mode_lock:
        for r in reversed(_execution_log):
            if (
                r.ticker == ticker
                and r.direction == direction
                and r.quantity == quantity
                and r.status == "pending_approval"
            ):
                global _mode
                saved_mode = _mode
                _mode = TradeMode.AUTO
                try:
                    result = await execute_order(
                        ticker=r.ticker,
                        direction=r.direction,
                        quantity=r.quantity,
                        price=r.price,
                        reason=r.reason,
                    )
                finally:
                    _mode = saved_mode
                return result
    return None


def cancel_pending(ticker: str) -> bool:
    for r in _execution_log:
        if r.ticker == ticker and r.status == "pending_approval":
            r.status = "cancelled"
            logger.info("Pending order cancelled: %s", ticker)
            return True
    return False
