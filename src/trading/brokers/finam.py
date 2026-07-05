from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from src.core.resilience import CircuitBreakerOpenError, get_circuit_breaker
from src.trading.brokers.base import (
    BaseBrokerClient,
    BrokerAccount,
    BrokerOrderResult,
    BrokerPosition,
)
from src.trading.brokers.registry import register_broker
from src.trading.types import OrderType, TimeInForce

logger = logging.getLogger(__name__)

FINAM_BASE_URL = "https://trade-api.finam.ru"
FINAM_BASE_URL_DEV = "https://trade-api-dev.finam.ru"


class FinamClient(BaseBrokerClient):
    def __init__(self, token: str = "", use_sandbox: bool = True):
        super().__init__(token, use_sandbox)
        self._base_url = FINAM_BASE_URL_DEV if use_sandbox else FINAM_BASE_URL
        self._http_client: Optional[httpx.AsyncClient] = None
        self._access_token: str = token
        self._refresh_token: str = ""

    @property
    def name(self) -> str:
        return "finam"

    async def __aenter__(self) -> FinamClient:
        self._http_client = httpx.AsyncClient(base_url=self._base_url, timeout=30)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._http_client:
            raise RuntimeError("Client not initialized")
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._access_token}"
        headers["X-Api-Key"] = self._token
        cb = get_circuit_breaker("finam")
        try:

            async def _do() -> Any:
                resp = await self._http_client.request(method, path, headers=headers, **kwargs)
                resp.raise_for_status()
                return resp.json()

            return await cb.call(_do)
        except CircuitBreakerOpenError:
            raise RuntimeError("Finam circuit breaker open")

    async def get_accounts(self) -> list[BrokerAccount]:
        data = await self._request("GET", "/api/v1/accounts")
        return [
            BrokerAccount(
                id=str(a.get("id", "")),
                name=a.get("name", ""),
                type=a.get("type", "finam"),
                status=a.get("status", "active"),
            )
            for a in (data if isinstance(data, list) else data.get("accounts", []))
        ]

    async def get_portfolio(self, account_id: str) -> list[BrokerPosition]:
        data = await self._request("GET", f"/api/v1/portfolio/{account_id}")
        return [
            BrokerPosition(
                figi=p.get("figi", ""),
                ticker=p.get("ticker", ""),
                instrument_type=p.get("type", ""),
                quantity=float(p.get("quantity", 0)),
                average_price=float(p.get("avgPrice", 0)),
                current_price=float(p.get("currentPrice", 0)),
            )
            for p in (data if isinstance(data, list) else data.get("positions", []))
        ]

    async def get_account_balance(self, account_id: str) -> float:
        data = await self._request("GET", f"/api/v1/portfolio/{account_id}")
        return float(data.get("balance", 0))

    async def place_order(
        self,
        figi: str,
        quantity: int,
        direction: str,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        account_id: str = "",
        idempotency_key: Optional[str] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ) -> BrokerOrderResult:
        side = "BUY" if direction.upper() in ("BUY", "COVER") else "SELL"
        body: dict[str, Any] = {
            "figi": figi,
            "quantity": quantity,
            "side": side,
            "orderType": order_type.value.upper(),
            "accountId": account_id,
        }
        if price is not None:
            body["price"] = price
        if idempotency_key:
            body["idempotencyKey"] = idempotency_key
        data = await self._request("POST", "/api/v1/orders", json=body)
        return BrokerOrderResult(
            order_id=str(data.get("orderId", "")),
            figi=figi,
            direction=direction,
            order_type=order_type.value,
            executed_price=float(data.get("executedPrice", 0)),
            executed_quantity=int(data.get("executedQuantity", 0)),
            total_commission=float(data.get("commission", 0)),
            status=str(data.get("status", "submitted")),
            idempotency_key=idempotency_key or "",
        )

    async def cancel_order(self, account_id: str, order_id: str) -> bool:
        try:
            await self._request("DELETE", f"/api/v1/orders/{account_id}/{order_id}")
            return True
        except Exception as e:
            logger.warning("Finam cancel_order failed: %s", e)
            return False

    async def get_orderbook(self, figi: str, depth: int = 10) -> Optional[dict[str, Any]]:
        return await self._request("GET", f"/api/v1/orderbook/{figi}?depth={depth}")

    async def get_instruments(self, instrument_type: str = "share") -> list[dict[str, Any]]:
        data = await self._request("GET", f"/api/v1/instruments?type={instrument_type}&limit=100")
        return data if isinstance(data, list) else data.get("instruments", [])

    async def get_candles(
        self,
        figi: str,
        interval: str = "hour",
        days: int = 30,
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        from_ts = now - timedelta(days=days)
        data = await self._request(
            "GET",
            f"/api/v1/candles/{figi}",
            params={
                "from": from_ts.isoformat(),
                "to": now.isoformat(),
                "interval": interval,
            },
        )
        return data if isinstance(data, list) else data.get("candles", [])


register_broker("finam", FinamClient)
