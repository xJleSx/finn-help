import logging
from datetime import datetime, timezone

from src.db.connection import get_session
from src.db.models import Order as OrderModel, TradeLog

logger = logging.getLogger(__name__)


def save_order(order: "OrderRecord") -> int:
    db = get_session()
    try:
        from src.execution.engine import OrderRecord

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
):
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
    except Exception as e:
        db.rollback()
        logger.error("Failed to log trade: %s", e)
    finally:
        db.close()


def get_trade_history(limit: int = 50) -> list[dict]:
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


def get_order_history(limit: int = 50) -> list[dict]:
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


def update_order_status(order_id: int, status: str, **kwargs):
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
