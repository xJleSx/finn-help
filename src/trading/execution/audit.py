from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from src.db.connection import get_session
from src.db.models import Order as OrderModel, TradeLog

logger = logging.getLogger(__name__)

AUDIT_DIR = Path(__file__).resolve().parents[2] / "data" / "audit"


def _ensure_audit_dir() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _audit_log_file() -> Path:
    _ensure_audit_dir()
    return AUDIT_DIR / f"orders_{datetime.now(timezone.utc).strftime('%Y_%m')}.jsonl"


def audit_log_order(entry: dict[str, object]) -> None:
    file_path = _audit_log_file()
    entry["_timestamp"] = datetime.now(timezone.utc).isoformat()
    entry["_id"] = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{os.urandom(4).hex()}"
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        logger.error("Failed to write audit log: %s", e)


def save_order(order: "OrderRecord") -> int:  # type: ignore[name-defined]
    db = get_session()
    try:
        from src.trading.execution.engine import OrderRecord

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
        logger.info("Order saved to DB: %s %s %d @ %.2f", order.direction, order.ticker, order.quantity, order.price)

        audit_log_order({
            "event": "order_saved",
            "id": o.id,
            "ticker": order.ticker,
            "direction": order.direction,
            "quantity": order.quantity,
            "price": order.price,
            "status": order.status,
            "mode": order.mode.value if hasattr(order.mode, "value") else str(order.mode),
            "reason": order.reason,
        })

        return o.id
    except Exception as e:
        db.rollback()
        logger.error("Failed to save order: %s", e)
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
        logger.info("Trade logged: %s %d %s @ %.2f (P&L=%.2f)", direction, quantity, ticker, price, pnl)

        audit_log_order({
            "event": "trade_logged",
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
        })
    except Exception as e:
        db.rollback()
        logger.error("Failed to log trade: %s", e)
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
            o.status = status
            for k, v in kwargs.items():
                if hasattr(o, k):
                    setattr(o, k, v)
            db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to update order %d: %s", order_id, e)
    finally:
        db.close()
