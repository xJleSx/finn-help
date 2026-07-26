import logging
from typing import Any, Optional

from src.db.connection import get_session
from src.db.models import Order as OrderModel

logger = logging.getLogger(__name__)


class PositionTracker:
    def __init__(self) -> None:
        self._positions: dict[str, dict[str, Any]] = {}
        self._short_positions: dict[str, dict[str, Any]] = {}
        self._restore_from_db()

    @staticmethod
    def _table_exists(db: Any) -> bool:
        try:
            db.execute("SELECT 1 FROM orders LIMIT 1")
            return True
        except Exception:
            return False

    def _restore_from_db(self) -> None:
        db = get_session()
        try:
            if not self._table_exists(db):
                logger.info("orders table not found — starting with empty positions")
                return
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

            short_filled = (
                db.query(OrderModel)
                .filter(
                    OrderModel.status.in_(["filled", "partial"]),
                    OrderModel.is_short.is_(True),
                )
                .all()
            )
            for o in short_filled:
                self._short_positions[str(o.ticker)] = {
                    "shares": int(o.quantity or 0),
                    "avg_price": float(o.price or 0.0),
                    "sl": o.stop_loss,
                    "tp": o.take_profit,
                }
            if self._positions or self._short_positions:
                logger.info("Restored %d long + %d short positions from DB", len(self._positions), len(self._short_positions))
        except Exception as e:
            logger.warning("Failed to restore positions from DB: %s", e)
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

    def add_short(self, ticker: str, quantity: int, price: float) -> None:
        if ticker not in self._short_positions:
            self._short_positions[ticker] = {"shares": 0, "avg_price": 0.0, "sl": None, "tp": None}
        pos = self._short_positions[ticker]
        total_value = float(pos["avg_price"]) * int(pos["shares"]) + price * quantity
        pos["shares"] = int(pos["shares"]) + quantity
        shares = int(pos["shares"])
        pos["avg_price"] = total_value / shares if shares > 0 else 0
        logger.info("Short position opened: %s %d @ %.2f", ticker, quantity, price)

    def cover_short(self, ticker: str, quantity: int, price: float) -> Optional[float]:
        pos = self._short_positions.get(ticker)
        if not pos or pos["shares"] == 0:
            return None
        cover_qty = min(quantity, int(pos["shares"]))
        pnl = (float(pos["avg_price"]) - price) * cover_qty
        pos["shares"] = int(pos["shares"]) - cover_qty
        if pos["shares"] <= 0:
            self._short_positions.pop(ticker, None)
        logger.info("Short position covered: %s %d @ %.2f (pnl=%.2f)", ticker, cover_qty, price, pnl)
        return pnl

    def get_short_positions(self) -> dict[str, dict[str, Any]]:
        return dict(self._short_positions)

    def get_total_short_value(self, current_prices: dict[str, float]) -> float:
        total = 0.0
        for ticker, pos in self._short_positions.items():
            price = current_prices.get(ticker, float(pos["avg_price"]))
            total += int(pos["shares"]) * price
        return total

    def set_sl_tp(self, ticker: str, sl_pct: Optional[float] = None, tp_pct: Optional[float] = None) -> None:
        if ticker in self._positions:
            if sl_pct is not None:
                self._positions[ticker]["sl"] = float(self._positions[ticker]["avg_price"]) * (1 - abs(sl_pct))
            if tp_pct is not None:
                self._positions[ticker]["tp"] = float(self._positions[ticker]["avg_price"]) * (1 + abs(tp_pct))
            self._persist_sl_tp(ticker)
        if ticker in self._short_positions:
            if sl_pct is not None:
                self._short_positions[ticker]["sl"] = float(self._short_positions[ticker]["avg_price"]) * (1 + abs(sl_pct))
            if tp_pct is not None:
                self._short_positions[ticker]["tp"] = float(self._short_positions[ticker]["avg_price"]) * (1 - abs(tp_pct))
            self._persist_sl_tp(ticker)

    def _persist_sl_tp(self, ticker: str) -> None:
        for attempt in range(3):
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
                    pos = self._positions.get(ticker) if not o.is_short else self._short_positions.get(ticker)
                    if pos:
                        o.stop_loss = pos.get("sl")
                        o.take_profit = pos.get("tp")
                db.commit()
                return
            except Exception as e:
                db.rollback()
                logger.debug("SL/TP persist attempt %d/3 failed for %s: %s", attempt + 1, ticker, e)
                if attempt < 2:
                    import time as _time

                    _time.sleep(0.3 * (attempt + 1))
                else:
                    logger.warning("Failed to persist SL/TP for %s after 3 attempts", ticker)
            finally:
                db.close()

    def check_triggers(self, ticker: str, current_price: float) -> Optional[str]:
        pos = self._positions.get(ticker)
        if pos and pos["shares"] > 0:
            sl = pos.get("sl")
            tp = pos.get("tp")
            if sl is not None and current_price <= float(sl):
                logger.warning("STOP-LOSS TRIGGERED %s at %.2f (SL=%.2f)", ticker, current_price, float(sl))
                return "stop_loss"
            if tp is not None and current_price >= float(tp):
                logger.info("TAKE-PROFIT TRIGGERED %s at %.2f (TP=%.2f)", ticker, current_price, float(tp))
                return "take_profit"

        short_pos = self._short_positions.get(ticker)
        if short_pos and short_pos["shares"] > 0:
            sl = short_pos.get("sl")
            tp = short_pos.get("tp")
            if sl is not None and current_price >= float(sl):
                logger.warning("SHORT STOP-LOSS TRIGGERED %s at %.2f (SL=%.2f)", ticker, current_price, float(sl))
                return "short_stop_loss"
            if tp is not None and current_price <= float(tp):
                logger.info("SHORT TAKE-PROFIT TRIGGERED %s at %.2f (TP=%.2f)", ticker, current_price, float(tp))
                return "short_take_profit"
        return None

    async def execute_triggers(self, ticker: str, current_price: float) -> Optional[str]:
        from src.trading.execution.engine import execute_order as _execute_order

        trigger = self.check_triggers(ticker, current_price)
        if not trigger:
            return None

        pos = self._positions.get(ticker)
        short_pos = self._short_positions.get(ticker)

        if "short_" in (trigger or ""):
            if short_pos and short_pos["shares"] > 0:
                await _execute_order(
                    ticker=ticker,
                    direction="BUY",
                    quantity=int(short_pos["shares"]),
                    price=current_price,
                    reason=f"{trigger} at {current_price:.2f}",
                    is_short=True,
                )
                return trigger
        elif pos and pos["shares"] > 0:
            await _execute_order(
                ticker=ticker,
                direction="SELL",
                quantity=int(pos["shares"]),
                price=current_price,
                reason=f"{trigger} at {current_price:.2f}",
            )
            return trigger
        return None


position_tracker = PositionTracker()
