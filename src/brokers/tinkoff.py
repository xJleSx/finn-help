from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


class TinkoffBrokerError(Exception):
    ...


class TinkoffBroker:
    def __init__(self, token: str | None = None, sandbox: bool = True) -> None:
        self._token = token or settings.tinkoff_token
        self._sandbox = sandbox
        self._accounts: list[dict[str, Any]] = []

    def _require_token(self) -> None:
        if not self._token:
            raise TinkoffBrokerError("TINKOFF_TOKEN is not configured")

    def get_portfolio(self) -> list[dict[str, Any]]:
        self._require_token()
        if self._sandbox:
            return self._mock_portfolio()
        # TODO: real Tinkoff Invest API — OperationsService/GetPortfolio
        raise NotImplementedError("Real Tinkoff API not integrated yet")

    def get_positions(self) -> list[dict[str, Any]]:
        self._require_token()
        if self._sandbox:
            return self._mock_positions()
        # TODO: real Tinkoff Invest API — OperationsService/GetPositions
        raise NotImplementedError("Real Tinkoff API not integrated yet")

    def place_market_order(self, ticker: str, quantity: int, direction: str = "buy") -> dict[str, Any]:
        self._require_token()
        if self._sandbox:
            return self._mock_order_response(ticker, quantity, direction, "market")
        # TODO: real Tinkoff Invest API — OrdersService/PostOrder
        raise NotImplementedError("Real Tinkoff API not integrated yet")

    def place_limit_order(self, ticker: str, quantity: int, price: float, direction: str = "buy") -> dict[str, Any]:
        self._require_token()
        if self._sandbox:
            return self._mock_order_response(ticker, quantity, direction, "limit", price)
        # TODO: real Tinkoff Invest API — OrdersService/PostOrder
        raise NotImplementedError("Real Tinkoff API not integrated yet")

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self._require_token()
        if self._sandbox:
            return {"status": "cancelled", "order_id": order_id}
        # TODO: real Tinkoff Invest API — OrdersService/CancelOrder
        raise NotImplementedError("Real Tinkoff API not integrated yet")

    def get_orderbook(self, ticker: str, depth: int = 5) -> dict[str, Any]:
        self._require_token()
        if self._sandbox:
            return self._mock_orderbook(ticker, depth)
        # TODO: real Tinkoff Invest API — MarketDataService/GetOrderBook
        raise NotImplementedError("Real Tinkoff API not integrated yet")

    def sync_portfolio_to_db(self, db: Any) -> dict[str, Any]:
        self._require_token()
        holdings = self.get_portfolio()
        synced = 0
        errors: list[str] = []
        from src.db.models import Instrument, Portfolio

        for h in holdings:
            try:
                ticker = h.get("ticker", "")
                instrument = db.query(Instrument).filter_by(ticker=ticker).first()
                if not instrument:
                    errors.append(f"Instrument not found: {ticker}")
                    continue
                existing = db.query(Portfolio).filter_by(instrument_id=instrument.id).first()
                qty = h.get("quantity", 0)
                avg = h.get("average_price")
                if existing:
                    existing.quantity = qty
                    if avg is not None:
                        existing.avg_price = avg
                else:
                    pos = Portfolio(instrument_id=instrument.id, quantity=qty, avg_price=avg)
                    db.add(pos)
                db.commit()
                synced += 1
            except Exception as e:
                db.rollback()
                errors.append(f"{h.get('ticker', '?')}: {e}")
        return {"synced": synced, "errors": errors}

    def _mock_portfolio(self) -> list[dict[str, Any]]:
        fake_holdings = [
            {"ticker": "SBER", "quantity": 100, "average_price": 280.0, "currency": "RUB"},
            {"ticker": "GAZP", "quantity": 50, "average_price": 165.0, "currency": "RUB"},
            {"ticker": "LKOH", "quantity": 10, "average_price": 7100.0, "currency": "RUB"},
        ]
        for h in fake_holdings:
            h["current_price"] = round(h["average_price"] * random.uniform(0.95, 1.05), 2)
            h["total_value"] = round(h["current_price"] * h["quantity"], 2)
            h["profit_pct"] = round((h["current_price"] / h["average_price"] - 1) * 100, 2)
        return fake_holdings

    def _mock_positions(self) -> list[dict[str, Any]]:
        return [
            {"ticker": "SBER", "quantity_lots": 1, "quantity": 100, "current_price": 295.5},
            {"ticker": "GAZP", "quantity_lots": 1, "quantity": 50, "current_price": 172.3},
        ]

    def _mock_order_response(
        self, ticker: str, quantity: int, direction: str, order_type: str, price: float | None = None,
    ) -> dict[str, Any]:
        order_id = str(uuid.uuid4())
        base_price = price or 300.0
        return {
            "order_id": order_id,
            "ticker": ticker,
            "direction": direction.upper(),
            "quantity": quantity,
            "price": base_price,
            "order_type": order_type,
            "status": "filled",
            "executed_quantity": quantity,
            "executed_price": base_price,
            "commission": round(base_price * quantity * 0.0005, 2),
            "currency": "RUB",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _mock_orderbook(self, ticker: str, depth: int = 5) -> dict[str, Any]:
        base = 300.0 if ticker == "SBER" else random.uniform(100, 1000)
        bids = [
            {"price": round(base - i * 0.5 - random.uniform(0, 0.3), 2), "quantity": random.randint(10, 500)}
            for i in range(depth)
        ]
        asks = [
            {"price": round(base + i * 0.5 + random.uniform(0, 0.3), 2), "quantity": random.randint(10, 500)}
            for i in range(depth)
        ]
        return {
            "ticker": ticker,
            "depth": depth,
            "bids": bids,
            "asks": asks,
            "last_price": base,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
