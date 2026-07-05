from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from src.trading.brokers.base import (
    BaseBrokerClient,
    BrokerAccount,
    BrokerOrderResult,
    BrokerPosition,
)
from src.trading.brokers.registry import register_broker
from src.trading.types import OrderType, TimeInForce

logger = logging.getLogger(__name__)


class OpenAPIClient(BaseBrokerClient):
    def __init__(self, token: str = "", use_sandbox: bool = True):
        super().__init__(token, use_sandbox)
        self._base_url = "https://api.example-broker.com/v1"
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "openapi"

    async def __aenter__(self) -> OpenAPIClient:
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
        headers["Authorization"] = f"Bearer {self._token}"
        headers["Content-Type"] = "application/json"
        resp = await self._http_client.request(method, path, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def get_accounts(self) -> list[BrokerAccount]:
        data = await self._request("GET", "/accounts")
        return [
            BrokerAccount(
                id=str(a.get("id", "")),
                name=a.get("name", ""),
                type=a.get("type", ""),
                status=a.get("status", "active"),
            )
            for a in data.get("accounts", [])
        ]

    async def get_portfolio(self, account_id: str) -> list[BrokerPosition]:
        data = await self._request("GET", f"/portfolio/{account_id}")
        return [
            BrokerPosition(
                figi=p.get("figi", ""),
                ticker=p.get("ticker", ""),
                instrument_type=p.get("type", ""),
                quantity=float(p.get("quantity", 0)),
                average_price=float(p.get("avgPrice", 0)),
                current_price=float(p.get("currentPrice", 0)),
            )
            for p in data.get("positions", [])
        ]

    async def get_account_balance(self, account_id: str) -> float:
        data = await self._request("GET", f"/portfolio/{account_id}")
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
        side = "buy" if direction.upper() in ("BUY", "COVER") else "sell"
        body: dict[str, Any] = {
            "figi": figi,
            "quantity": quantity,
            "side": side,
            "orderType": order_type.value,
            "accountId": account_id,
            "timeInForce": time_in_force.value,
        }
        if price is not None:
            body["price"] = str(price)
        if idempotency_key:
            body["idempotencyKey"] = idempotency_key
        data = await self._request("POST", "/orders", json=body)
        return BrokerOrderResult(
            order_id=str(data.get("orderId", "")),
            figi=figi,
            direction=direction,
            order_type=order_type.value,
            executed_price=float(data.get("executedPrice", 0)),
            executed_quantity=int(data.get("executedQuantity", 0)),
            total_commission=float(data.get("commission", 0)),
            status=str(data.get("status", "submitted")),
            filled_quantity=int(data.get("filledQuantity", 0)),
            remaining_quantity=int(data.get("remainingQuantity", 0)),
            idempotency_key=idempotency_key or "",
        )

    async def cancel_order(self, account_id: str, order_id: str) -> bool:
        try:
            await self._request("DELETE", f"/orders/{account_id}/{order_id}")
            return True
        except Exception as e:
            logger.warning("OpenAPI cancel_order failed: %s", e)
            return False

    async def get_orderbook(self, figi: str, depth: int = 10) -> Optional[dict[str, Any]]:
        return await self._request("GET", f"/orderbook/{figi}?depth={depth}")

    async def get_instruments(self, instrument_type: str = "share") -> list[dict[str, Any]]:
        data = await self._request("GET", f"/instruments?type={instrument_type}&limit=100")
        return data.get("instruments", [])

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
            f"/candles/{figi}",
            params={
                "from": from_ts.isoformat(),
                "to": now.isoformat(),
                "interval": interval,
            },
        )
        return data.get("candles", [])


register_broker("openapi", OpenAPIClient)
