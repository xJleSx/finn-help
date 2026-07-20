from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from src.core.context import context_extra
from src.db.connection import get_session
from src.db.models import ComplianceEvent, OrderFill
from src.db.models import Order as OrderModel

if TYPE_CHECKING:
    from src.trading.execution.engine import OrderRecord
from src.db.models import TradeLog

logger = structlog.get_logger(__name__)

AUDIT_DIR = Path(__file__).resolve().parents[2] / "data" / "audit"
MAX_AUDIT_BYTES = 10 * 1024 * 1024


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
    now = datetime.now(timezone.utc)
    entry["_timestamp"] = now.isoformat()
    entry["_event_id"] = str(uuid.uuid4())
    entry["_event_date"] = now.strftime("%Y-%m-%d")
    entry["_event_time"] = now.strftime("%H:%M:%S.%f")[:-3]
    entry["_source"] = "finn-help"
    entry["_version"] = "0.2.0"
    entry.update(context_extra())
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
        logger.info("audit.order", **entry)
    except Exception as e:
        logger.error("Failed to write audit log", error=str(e))


def save_order(order: "OrderRecord") -> int:
    db = get_session()
    try:
        kw = dict(
            ticker=order.ticker,
            direction=order.direction,
            quantity=order.quantity,
            price=order.price,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            status=order.status,
            mode=order.mode.value if hasattr(order.mode, "value") else str(order.mode),
            reason=order.reason,
            order_id_ext=order.order_id,
            is_short=order.is_short,
            filled_quantity=order.filled_quantity,
            remaining_quantity=order.remaining_quantity,
            executed_price=order.executed_price,
            commission=order.commission,
            created_at=order.created_at,
        )
        try:
            o = OrderModel(**kw)
            db.add(o)
            db.commit()
        except OperationalError:
            db.rollback()
            kw.pop("time_in_force", None)
            o = OrderModel(**kw)
            db.add(o)
            db.commit()
        logger.info(
            "order_saved",
            ticker=order.ticker,
            direction=order.direction,
            quantity=order.quantity,
            price=order.price,
            status=order.status,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            is_short=order.is_short,
            mode=order.mode.value if hasattr(order.mode, "value") else str(order.mode),
        )

        audit_entry = {
            "event": "order_saved",
            "order_type": order.order_type,
            "time_in_force": order.time_in_force,
            "id": o.id,
            "ticker": order.ticker,
            "direction": order.direction,
            "quantity": order.quantity,
            "price": order.price,
            "status": order.status,
            "mode": order.mode.value if hasattr(order.mode, "value") else str(order.mode),
            "reason": order.reason,
            "is_short": order.is_short,
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
    is_short: bool = False,
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
            is_short=is_short,
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
            "is_short": is_short,
        }
        audit_log_order(audit_entry)
    except Exception as e:
        db.rollback()
        logger.error("trade_log_failed", ticker=ticker, error=str(e))
    finally:
        db.close()


def log_order_fill(order_id: int, quantity: int, price: float, commission: float = 0.0) -> None:
    db = get_session()
    try:
        fill = OrderFill(
            order_id=order_id,
            quantity=quantity,
            price=price,
            commission=commission,
        )
        db.add(fill)
        db.commit()
        logger.info("order_fill_logged", order_id=order_id, quantity=quantity, price=price)
    except Exception as e:
        db.rollback()
        logger.error("order_fill_log_failed", order_id=order_id, error=str(e))
    finally:
        db.close()


def log_compliance_event(
    user_id: int,
    event_type: str,
    ticker: str = "",
    details: str = "",
    severity: str = "info",
) -> None:
    db = get_session()
    try:
        event = ComplianceEvent(
            user_id=user_id,
            event_type=event_type,
            ticker=ticker,
            details=details,
            severity=severity,
        )
        db.add(event)
        db.commit()
        logger.warning(
            "compliance_event",
            user_id=user_id,
            event_type=event_type,
            ticker=ticker,
            severity=severity,
        )
        audit_log_order(
            {
                "event": "compliance_event",
                "user_id": user_id,
                "event_type": event_type,
                "ticker": ticker or "",
                "severity": severity,
                "details": details,
            }
        )
    except Exception as e:
        db.rollback()
        logger.error("compliance_event_failed", error=str(e))
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
                "order_type": o.order_type,
                "time_in_force": o.time_in_force,
                "status": o.status,
                "mode": o.mode,
                "reason": o.reason,
                "created_at": o.created_at.isoformat(),
                "order_id_ext": o.order_id_ext,
                "commission": o.commission,
                "executed_price": o.executed_price,
                "filled_quantity": o.filled_quantity,
                "remaining_quantity": o.remaining_quantity,
                "is_short": o.is_short,
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
            o.status = status
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
            audit_log_order(
                {
                    "event": "order_status_changed",
                    "order_id": order_id,
                    "ticker": o.ticker,
                    "old_status": old_status,
                    "new_status": status,
                    "changes": {k: str(v) for k, v in kwargs.items()},
                }
            )
    except Exception as e:
        db.rollback()
        logger.error("order_update_failed", order_id=order_id, error=str(e))
    finally:
        db.close()
