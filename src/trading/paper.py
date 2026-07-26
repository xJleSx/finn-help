from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.trading.metrics import PerformanceMetrics, compute_metrics

logger = logging.getLogger(__name__)

PAPER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "paper")

DEFAULT_INITIAL_CAPITAL = 1_000_000.0
DEFAULT_COMMISSION_PCT = 0.0004
DEFAULT_SLIPPAGE_BPS = 5


@dataclass
class PaperPosition:
    ticker: str
    quantity: float
    avg_price: float


@dataclass
class PaperShortPosition:
    ticker: str
    quantity: float
    avg_price: float
    margin_held: float = 0.0


@dataclass
class PaperTradeRecord:
    timestamp: str
    ticker: str
    direction: str
    quantity: float
    price: float
    commission: float
    slippage: float
    pnl: float
    balance_before: float
    balance_after: float
    reason: str = ""
    is_short: bool = False


@dataclass
class PaperState:
    balance: float
    initial_capital: float
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    short_positions: dict[str, PaperShortPosition] = field(default_factory=dict)
    equity_history: list[float] = field(default_factory=list)
    trades: list[PaperTradeRecord] = field(default_factory=list)
    start_time: str = ""
    last_price_cache: dict[str, float] = field(default_factory=dict)
    margin_loan: float = 0.0
    leverage: float = 1.0

    def total_equity(self, current_prices: dict[str, float] | None = None) -> float:
        pos_value = 0.0
        short_value = 0.0
        prices = current_prices or self.last_price_cache
        for t, pos in self.positions.items():
            price = prices.get(t, pos.avg_price)
            pos_value += pos.quantity * price
        for t, pos in self.short_positions.items():
            price = prices.get(t, pos.avg_price)
            short_value += pos.quantity * price
        return self.balance + pos_value - short_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance": self.balance,
            "initial_capital": self.initial_capital,
            "positions": {t: {"ticker": p.ticker, "quantity": p.quantity, "avg_price": p.avg_price} for t, p in self.positions.items()},
            "short_positions": {
                t: {"ticker": p.ticker, "quantity": p.quantity, "avg_price": p.avg_price, "margin_held": p.margin_held}
                for t, p in self.short_positions.items()
            },
            "equity_history": self.equity_history[-500:],
            "n_trades": len(self.trades),
            "start_time": self.start_time,
            "last_price_cache": self.last_price_cache,
            "margin_loan": self.margin_loan,
            "leverage": self.leverage,
        }


class PaperTradingEngine:
    def __init__(self, user_id: int = 0) -> None:
        self.user_id = user_id
        if not isinstance(user_id, int) or user_id < 0:
            raise ValueError(f"Invalid user_id: {user_id}")
        self._state: PaperState | None = None
        resolved = (Path(PAPER_DIR) / f"user_{user_id}.json").resolve()
        if not str(resolved).startswith(str(Path(PAPER_DIR).resolve())):
            raise ValueError("Invalid user_id path")
        self._state_path = str(resolved)

    # ── State management ──────────────────────────────────────────────

    def _load_state(self) -> PaperState:
        if self._state is not None:
            return self._state
        try:
            os.makedirs(PAPER_DIR, exist_ok=True)
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            positions = {}
            for t, pdata in data.get("positions", {}).items():
                positions[t] = PaperPosition(
                    ticker=pdata.get("ticker", t), quantity=float(pdata.get("quantity", 0)), avg_price=float(pdata.get("avg_price", 0.0))
                )
            short_positions = {}
            for t, pdata in data.get("short_positions", {}).items():
                short_positions[t] = PaperShortPosition(
                    ticker=pdata.get("ticker", t),
                    quantity=float(pdata.get("quantity", 0)),
                    avg_price=float(pdata.get("avg_price", 0.0)),
                    margin_held=float(pdata.get("margin_held", 0)),
                )
            self._state = PaperState(
                balance=float(data.get("balance", DEFAULT_INITIAL_CAPITAL)),
                initial_capital=float(data.get("initial_capital", DEFAULT_INITIAL_CAPITAL)),
                positions=positions,
                short_positions=short_positions,
                equity_history=[float(x) for x in data.get("equity_history", [])],
                trades=[PaperTradeRecord(**t) if isinstance(t, dict) else t for t in data.get("trades", [])],
                start_time=str(data.get("start_time", "")),
                last_price_cache={k: float(v) for k, v in data.get("last_price_cache", {}).items()},
                margin_loan=float(data.get("margin_loan", 0)),
                leverage=float(data.get("leverage", 1.0)),
            )
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            logger.warning("Corrupted or missing paper state file at %s: %s", self._state_path, e)
            if os.path.exists(self._state_path):
                backup_path = self._state_path + ".corrupt"
                try:
                    os.replace(self._state_path, backup_path)
                    logger.warning("Backed up corrupt state to %s", backup_path)
                except OSError as be:
                    logger.warning("Failed to back up corrupt state: %s", be)
            self._state = PaperState(
                balance=DEFAULT_INITIAL_CAPITAL,
                initial_capital=DEFAULT_INITIAL_CAPITAL,
                start_time=datetime.now(timezone.utc).isoformat(),
            )
        return self._state

    def _save_state(self) -> None:
        if self._state is None:
            return
        os.makedirs(PAPER_DIR, exist_ok=True)
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)

    def clear_cache(self) -> None:
        self._state = None

    # ── Public API ────────────────────────────────────────────────────

    def get_state(self) -> PaperState:
        return self._load_state()

    def reset(self, initial_capital: float = DEFAULT_INITIAL_CAPITAL) -> PaperState:
        old_path = self._state_path
        if os.path.exists(old_path):
            backup = old_path + ".bak"
            with contextlib.suppress(OSError):
                os.replace(old_path, backup)
        self._state = PaperState(
            balance=initial_capital,
            initial_capital=initial_capital,
            start_time=datetime.now(timezone.utc).isoformat(),
        )
        self._save_state()
        logger.info("Paper account reset to %.2f", initial_capital)
        return self._state

    def get_balance(self) -> float:
        return self._load_state().balance

    def get_positions(self) -> dict[str, PaperPosition]:
        return dict(self._load_state().positions)

    def get_equity(self, current_prices: dict[str, float] | None = None) -> float:
        return self._load_state().total_equity(current_prices)

    def get_equity_history(self) -> list[float]:
        return list(self._load_state().equity_history)

    def get_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        trades = self._load_state().trades
        return [self._trade_to_dict(t) for t in trades[-limit:]]

    def get_metrics(self, current_prices: dict[str, float] | None = None) -> PerformanceMetrics:
        state = self._load_state()
        if len(state.equity_history) < 5:
            prices = current_prices or state.last_price_cache
            current_equity = state.total_equity(prices)
            history = [state.initial_capital, current_equity] if current_equity != state.initial_capital else [state.initial_capital]
        else:
            history = list(state.equity_history)
        trade_dicts = [self._trade_to_dict(t) for t in state.trades]
        return compute_metrics(history, trades=trade_dicts)

    def update_prices(self, prices: dict[str, float]) -> None:
        state = self._load_state()
        state.last_price_cache.update(prices)
        equity = state.total_equity(prices)
        state.equity_history.append(equity)
        self._save_state()

    # ── Order execution ───────────────────────────────────────────────

    def execute_order(
        self,
        ticker: str,
        direction: str,
        quantity: float,
        price: float | None = None,
        reason: str = "",
        commission_pct: float | None = None,
        slippage_bps: int | None = None,
        current_prices: dict[str, float] | None = None,
        is_short: bool = False,
    ) -> dict[str, Any]:
        state = self._load_state()
        ticker = ticker.upper()
        direction = direction.upper()
        if direction not in ("BUY", "SELL", "SHORT", "COVER"):
            return {"status": "error", "error": f"Invalid direction: {direction}"}

        if price is None or price <= 0:
            price = state.last_price_cache.get(ticker, 0.0)
            if price <= 0:
                return {"status": "error", "error": f"No price available for {ticker}"}

        if quantity <= 0:
            return {"status": "error", "error": "Quantity must be positive"}

        com_pct = commission_pct if commission_pct is not None else DEFAULT_COMMISSION_PCT
        slip_bps = slippage_bps if slippage_bps is not None else DEFAULT_SLIPPAGE_BPS

        gross_value = quantity * price
        commission = gross_value * com_pct
        slippage = gross_value * (slip_bps / 10_000)
        total_cost = gross_value + commission + slippage

        balance_before = state.balance
        pnl = 0.0
        effective_is_short = is_short or direction in ("SHORT",)
        effective_is_cover = direction in ("COVER",)

        if direction in ("BUY", "COVER"):
            if effective_is_cover:
                short_pos = state.short_positions.get(ticker)
                if not short_pos or short_pos.quantity < 1e-10:
                    return {"status": "error", "error": f"No short position in {ticker} to cover"}
                if quantity > short_pos.quantity:
                    quantity = short_pos.quantity
                    gross_value = quantity * price
                    commission = gross_value * com_pct
                    slippage = gross_value * (slip_bps / 10_000)
                    total_cost = gross_value + commission + slippage
                cost_basis = quantity * short_pos.avg_price
                pnl = cost_basis - gross_value
                new_balance = balance_before - gross_value - commission - slippage
                remaining = short_pos.quantity - quantity
                if remaining < 1e-10:
                    state.short_positions.pop(ticker, None)
                else:
                    state.short_positions[ticker] = PaperShortPosition(ticker=ticker, quantity=remaining, avg_price=short_pos.avg_price)
                state.balance = new_balance
            else:
                if total_cost > balance_before:
                    max_qty = int(balance_before / (price * (1 + com_pct + slip_bps / 10_000)))
                    if max_qty < 1:
                        return {"status": "error", "error": f"Insufficient funds: need {total_cost:.2f}, have {balance_before:.2f}"}
                    quantity = max_qty
                    gross_value = quantity * price
                    commission = gross_value * com_pct
                    slippage = gross_value * (slip_bps / 10_000)
                    total_cost = gross_value + commission + slippage
                new_balance = balance_before - total_cost
                existing = state.positions.get(ticker)
                if existing:
                    total_qty = existing.quantity + quantity
                    total_cost_basis = existing.quantity * existing.avg_price + gross_value
                    state.positions[ticker] = PaperPosition(ticker=ticker, quantity=total_qty, avg_price=total_cost_basis / total_qty)
                else:
                    state.positions[ticker] = PaperPosition(ticker=ticker, quantity=quantity, avg_price=price)
                state.balance = new_balance
            state.last_price_cache[ticker] = price

        elif direction in ("SELL", "SHORT"):
            if effective_is_short:
                margin_required = gross_value * 0.5
                if balance_before < margin_required:
                    return {"status": "error", "error": f"Insufficient margin for short: need {margin_required:.2f}, have {balance_before:.2f}"}
                proceeds = gross_value
                new_balance = balance_before + proceeds - commission - slippage
                existing_short = state.short_positions.get(ticker)
                if existing_short:
                    total_qty = existing_short.quantity + quantity
                    total_avg = (existing_short.quantity * existing_short.avg_price + quantity * price) / total_qty
                    state.short_positions[ticker] = PaperShortPosition(
                        ticker=ticker, quantity=total_qty, avg_price=total_avg, margin_held=existing_short.margin_held + margin_required
                    )
                else:
                    state.short_positions[ticker] = PaperShortPosition(ticker=ticker, quantity=quantity, avg_price=price, margin_held=margin_required)
                state.balance = new_balance
            else:
                pos = state.positions.get(ticker)
                if not pos or pos.quantity < 1e-10:
                    return {"status": "error", "error": f"No position in {ticker} to sell"}
                cost_basis = quantity * pos.avg_price
                if quantity > pos.quantity:
                    quantity = pos.quantity
                    gross_value = quantity * price
                    commission = gross_value * com_pct
                    slippage = gross_value * (slip_bps / 10_000)
                    cost_basis = quantity * pos.avg_price
                net_proceeds = gross_value - commission - slippage
                pnl = net_proceeds - cost_basis
                new_balance = balance_before + net_proceeds
                remaining = pos.quantity - quantity
                if remaining < 1e-10:
                    state.positions.pop(ticker, None)
                else:
                    state.positions[ticker] = PaperPosition(ticker=ticker, quantity=remaining, avg_price=pos.avg_price)
                state.balance = new_balance
            state.last_price_cache[ticker] = price

        record = PaperTradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            ticker=ticker,
            direction=direction,
            quantity=quantity,
            price=price,
            commission=commission,
            slippage=slippage,
            pnl=pnl,
            balance_before=balance_before,
            balance_after=state.balance,
            reason=reason,
            is_short=effective_is_short,
        )
        state.trades.append(record)

        equity = state.total_equity(current_prices or state.last_price_cache)
        state.equity_history.append(equity)

        self._save_state()

        logger.info(
            "PAPER %s %s %.2f @ %.2f (pnl=%.2f, balance=%.2f)",
            direction,
            ticker,
            quantity,
            price,
            pnl,
            state.balance,
        )

        return {
            "status": "filled",
            "ticker": ticker,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "commission": commission,
            "slippage": slippage,
            "pnl": pnl,
            "balance_before": balance_before,
            "balance_after": state.balance,
            "total_equity": equity,
            "is_short": effective_is_short,
            "reason": reason,
        }

    def _trade_to_dict(self, t: PaperTradeRecord) -> dict[str, Any]:
        return {
            "timestamp": t.timestamp,
            "ticker": t.ticker,
            "direction": t.direction,
            "quantity": t.quantity,
            "price": t.price,
            "commission": t.commission,
            "slippage": t.slippage,
            "pnl": t.pnl,
            "balance_before": t.balance_before,
            "balance_after": t.balance_after,
            "reason": t.reason,
            "is_short": t.is_short,
        }
