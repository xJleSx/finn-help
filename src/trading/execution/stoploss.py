import logging
from typing import Any, Optional

from src.db.connection import get_session
from src.db.models import Order as OrderModel

logger = logging.getLogger(__name__)


class PositionTracker:
    def __init__(self) -> None:
        self._positions: dict[str, dict[str, Any]] = {}
        self._restore_from_db()

    def _restore_from_db(self) -> None:
        db = get_session()
        try:
            filled = (
                db.query(OrderModel)
                .filter(
                    OrderModel.status.in_(["filled", "partial"]),
                    OrderModel.direction == "BUY",
                )
                .all()
            )
            for o in filled:
                self._positions[str(o.ticker)] = {
                    "shares": int(o.quantity or 0),
                    "avg_price": float(o.price or 0.0),
                    "sl": o.stop_loss,
                    "tp": o.take_profit,
                }
        except Exception:
            pass
        finally:
            db.close()

    def update(self, ticker: str, direction: str, quantity: int, price: float) -> None:
        if ticker not in self._positions:
            self._positions[ticker] = {"shares": 0, "avg_price": 0.0, "sl": None, "tp": None}
        pos = self._positions[ticker]
        if direction == "BUY":
            total_cost = float(pos["avg_price"]) * int(pos["shares"]) + price * quantity
            pos["shares"] = int(pos["shares"]) + quantity
            shares = int(pos["shares"])
            pos["avg_price"] = total_cost / shares if shares > 0 else 0
        elif direction == "SELL":
            pos["shares"] = max(0, int(pos["shares"]) - quantity)
            if pos["shares"] == 0:
                pos["avg_price"] = 0.0
                self._positions.pop(ticker, None)

    def set_sl_tp(self, ticker: str, sl_pct: Optional[float] = None, tp_pct: Optional[float] = None) -> None:
        if ticker in self._positions:
            if sl_pct is not None:
                self._positions[ticker]["sl"] = float(self._positions[ticker]["avg_price"]) * (1 - abs(sl_pct))
            if tp_pct is not None:
                self._positions[ticker]["tp"] = float(self._positions[ticker]["avg_price"]) * (1 + abs(tp_pct))
            self._persist_sl_tp(ticker)

    def _persist_sl_tp(self, ticker: str) -> None:
        pos = self._positions.get(ticker)
        if not pos:
            return
        db = get_session()
        try:
            orders = (
                db.query(OrderModel)
                .filter(
                    OrderModel.ticker == ticker,
                    OrderModel.status.in_(["filled", "partial"]),
                )
                .all()
            )
            for o in orders:
                o.stop_loss = pos.get("sl")  # type: ignore[assignment]
                o.take_profit = pos.get("tp")  # type: ignore[assignment]
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def check_triggers(self, ticker: str, current_price: float) -> Optional[str]:
        pos = self._positions.get(ticker)
        if not pos or pos["shares"] == 0:
            return None

        sl = pos.get("sl")
        tp = pos.get("tp")

        if sl is not None and current_price <= float(sl):
            logger.warning("STOP-LOSS TRIGGERED %s at %.2f (SL=%.2f)", ticker, current_price, float(sl))
            return "stop_loss"
        if tp is not None and current_price >= float(tp):
            logger.info("TAKE-PROFIT TRIGGERED %s at %.2f (TP=%.2f)", ticker, current_price, float(tp))
            return "take_profit"
        return None

    async def execute_triggers(self, ticker: str, current_price: float) -> Optional[str]:
        from src.trading.execution.engine import execute_order as _execute_order

        trigger = self.check_triggers(ticker, current_price)
        if not trigger:
            return None

        pos = self._positions.get(ticker)
        if not pos or pos["shares"] == 0:
            return None

        await _execute_order(
            ticker=ticker,
            direction="SELL",
            quantity=int(pos["shares"]),
            price=current_price,
            reason=f"{trigger} at {current_price:.2f}",
        )
        return trigger


position_tracker = PositionTracker()
