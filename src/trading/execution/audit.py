from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from src.core.context import context_extra
from src.db.connection import get_session
from src.db.models import Order as OrderModel

if TYPE_CHECKING:
    from src.trading.execution.engine import OrderRecord
from src.db.models import TradeLog

logger = structlog.get_logger(__name__)

AUDIT_DIR = Path(__file__).resolve().parents[2] / "data" / "audit"
MAX_AUDIT_BYTES = 10 * 1024 * 1024  # 10 MB


def _ensure_audit_dir() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _audit_log_file() -> Path:
    _ensure_audit_dir()
    return AUDIT_DIR / f"orders_{datetime.now(timezone.utc).strftime('%Y_%m')}.jsonl"


def _rotate_if_needed(file_path: Path) -> None:
    try:
        if file_path.exists() and file_path.stat().st_size > MAX_AUDIT_BYTES:
            index = 1
            while True:
                rotated = file_path.with_name(f"{file_path.stem}_{index}{file_path.suffix}")
                if not rotated.exists():
                    break
                index += 1
            file_path.rename(rotated)
            logger.info("audit_rotated", src=str(file_path), dst=str(rotated))
    except OSError as e:
        logger.error("audit_rotation_failed: %s", e)


def _build_audit_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Build a standardized audit entry with full context."""
    now = datetime.now(timezone.utc)
    entry["_timestamp"] = now.isoformat()
    entry["_event_id"] = str(uuid.uuid4())
    entry["_event_date"] = now.strftime("%Y-%m-%d")
    entry["_event_time"] = now.strftime("%H:%M:%S.%f")[:-3]
    entry["_source"] = "finn-help"
    entry["_version"] = "0.1.0"

    # Add execution context
    entry.update(context_extra())

    # Ensure all trade-critical fields are present
    if "order_id" not in entry and "id" in entry:
        entry["order_id"] = entry["id"]
    return entry


def audit_log_order(entry: dict[str, object]) -> None:
    entry = _build_audit_entry(dict(entry))
    file_path = _audit_log_file()
    _rotate_if_needed(file_path)
    try:
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        # Also log to structlog for real-time observability
        logger.info("audit.order", **entry)
    except Exception as e:
        logger.error("Failed to write audit log", error=str(e))


def save_order(order: "OrderRecord") -> int:
    db = get_session()
    try:
        o = OrderModel(
            ticker=order.ticker,
            direction=order.direction,
            quantity=order.quantity,
            price=order.price,
            status=order.status,
            mode=order.mode.value if hasattr(order.mode, "value") else str(order.mode),
            reason=order.reason,
            order_id_ext=order.order_id,
            created_at=order.created_at,
        )
        db.add(o)
        db.commit()
        logger.info(
            "order_saved",
            ticker=order.ticker,
            direction=order.direction,
            quantity=order.quantity,
            price=order.price,
            status=order.status,
            mode=order.mode.value if hasattr(order.mode, "value") else str(order.mode),
        )

        audit_entry = {
            "event": "order_saved",
            "order_type": "market",
            "id": o.id,
            "ticker": order.ticker,
            "direction": order.direction,
            "quantity": order.quantity,
            "price": order.price,
            "status": order.status,
            "mode": order.mode.value if hasattr(order.mode, "value") else str(order.mode),
            "reason": order.reason,
        }
        if order.order_id:
            audit_entry["exchange_order_id"] = order.order_id
        audit_log_order(audit_entry)

        return int(o.id)
    except Exception as e:
        db.rollback()
        logger.error("order_save_failed", ticker=order.ticker, error=str(e))
        return 0
    finally:
        db.close()


def log_trade(
    ticker: str,
    direction: str,
    quantity: int,
    price: float,
    commission: float = 0.0,
    slippage: float = 0.0,
    pnl: float = 0.0,
    reason: str = "",
    order_id: int = 0,
) -> None:
    db = get_session()
    try:
        t = TradeLog(
            order_id=order_id or None,
            ticker=ticker,
            direction=direction,
            quantity=quantity,
            price=price,
            commission=commission,
            slippage=slippage,
            pnl=pnl,
            reason=reason,
        )
        db.add(t)
        db.commit()
        logger.info(
            "trade_logged",
            ticker=ticker,
            direction=direction,
            quantity=quantity,
            price=price,
            pnl=pnl,
            commission=commission,
        )

        audit_entry = {
            "event": "trade_executed",
            "id": t.id,
            "order_id": order_id,
            "ticker": ticker,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "commission": commission,
            "slippage": slippage,
            "pnl": pnl,
            "reason": reason,
        }
        audit_log_order(audit_entry)
    except Exception as e:
        db.rollback()
        logger.error("trade_log_failed", ticker=ticker, error=str(e))
    finally:
        db.close()


def get_trade_history(limit: int = 50) -> list[dict[str, object]]:
    db = get_session()
    try:
        trades = db.query(TradeLog).order_by(TradeLog.created_at.desc()).limit(limit).all()
        return [
            {
                "id": t.id,
                "date": t.created_at.isoformat(),
                "ticker": t.ticker,
                "direction": t.direction,
                "quantity": t.quantity,
                "price": t.price,
                "commission": t.commission,
                "pnl": t.pnl,
                "reason": t.reason,
            }
            for t in trades
        ]
    finally:
        db.close()


def get_order_history(limit: int = 50) -> list[dict[str, object]]:
    db = get_session()
    try:
        orders = db.query(OrderModel).order_by(OrderModel.created_at.desc()).limit(limit).all()
        return [
            {
                "id": o.id,
                "ticker": o.ticker,
                "direction": o.direction,
                "quantity": o.quantity,
                "price": o.price,
                "status": o.status,
                "mode": o.mode,
                "reason": o.reason,
                "created_at": o.created_at.isoformat(),
                "order_id_ext": o.order_id_ext,
                "commission": o.commission,
                "executed_price": o.executed_price,
                "stop_loss": o.stop_loss,
                "take_profit": o.take_profit,
            }
            for o in orders
        ]
    finally:
        db.close()


def update_order_status(order_id: int, status: str, **kwargs: object) -> None:
    db = get_session()
    try:
        o = db.query(OrderModel).filter_by(id=order_id).first()
        if o:
            old_status = o.status
            o.status = status  # type: ignore[assignment]
            for k, v in kwargs.items():
                if hasattr(o, k):
                    setattr(o, k, v)
            db.commit()
            logger.info(
                "order_status_updated",
                order_id=order_id,
                ticker=o.ticker,
                old_status=old_status,
                new_status=status,
            )
            audit_log_order({
                "event": "order_status_changed",
                "order_id": order_id,
                "ticker": o.ticker,
                "old_status": old_status,
                "new_status": status,
                "changes": {k: str(v) for k, v in kwargs.items()},
            })
    except Exception as e:
        db.rollback()
        logger.error("order_update_failed", order_id=order_id, error=str(e))
    finally:
        db.close()
