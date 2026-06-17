import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from src.brokers.tbank import TBankClient
from src.config import personal, settings
from src.execution.audit import log_trade, save_order, update_order_status

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


_execution_log: list[OrderRecord] = []
_mode: TradeMode = TradeMode.MANUAL


def set_mode(mode: TradeMode):
    global _mode
    _mode = mode
    logger.info("Trade mode set to %s", mode.value)


def get_mode() -> TradeMode:
    return _mode


def get_log(limit: int = 20) -> list[dict]:
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
        for r in _execution_log[-limit:]
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
        _execution_log.append(record)
        record.db_id = save_order(record)
        return record

    if not settings.tinkoff_token:
        record.status = "failed"
        logger.warning("No TINKOFF_TOKEN set, falling back to dry-run")
        record.mode = TradeMode.DRY_RUN
        record.status = "simulated"
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
        use_sandbox = settings.tinkoff_sandbox
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
                figi=figi or ticker,
                quantity=quantity,
                direction=direction,
                account_id=account_id,
            )
            record.order_id = result.get("order_id")
            record.status = result.get("status", "unknown")
            record.price = result.get("executed_price", record.price)
            logger.info("ORDER FILLED: %s %d %s at %.2f (id=%s)", direction, quantity, ticker, record.price, record.order_id)
    except Exception as e:
        record.status = "failed"
        logger.error("Order failed: %s %d %s: %s", direction, quantity, ticker, e, exc_info=True)

    _execution_log.append(record)
    record.db_id = save_order(record)
    return record


async def approve_order(ticker: str, direction: str, quantity: int) -> Optional[OrderRecord]:
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
            result = await execute_order(
                ticker=r.ticker,
                direction=r.direction,
                quantity=r.quantity,
                price=r.price,
                reason=r.reason,
            )
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
