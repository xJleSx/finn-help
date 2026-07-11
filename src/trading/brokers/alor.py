from __future__ import annotations

import logging
import time
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

ALOR_BASE_URL = "https://api.alor.ru"
ALOR_BASE_URL_DEV = "https://apidev.alor.ru"
ALOR_REFRESH_URL = "https://oauth.alor.ru/refresh"


class AlorClient(BaseBrokerClient):
    def __init__(self, token: str = "", use_sandbox: bool = True):
        super().__init__(token, use_sandbox)
        self._base_url = ALOR_BASE_URL_DEV if use_sandbox else ALOR_BASE_URL
        self._http_client: Optional[httpx.AsyncClient] = None
        self._refresh_token: str = ""
        self._token_expires_at: float = 0

    @property
    def name(self) -> str:
        return "alor"

    async def __aenter__(self) -> AlorClient:
        self._http_client = httpx.AsyncClient(base_url=self._base_url, timeout=30)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _ensure_token(self) -> None:
        if time.time() >= self._token_expires_at and self._refresh_token:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    ALOR_REFRESH_URL,
                    json={"refreshToken": self._refresh_token},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._token = data.get("accessToken", self._token)
                    self._refresh_token = data.get("refreshToken", self._refresh_token)
                    self._token_expires_at = time.time() + data.get("expiresIn", 3600)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._http_client:
            raise RuntimeError("Client not initialized")
        await self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token}"
        cb = get_circuit_breaker("alor")
        try:

            async def _do() -> Any:
                resp = await self._http_client.request(method, path, headers=headers, **kwargs)
                resp.raise_for_status()
                return resp.json()

            return await cb.call(_do)
        except CircuitBreakerOpenError:
            raise RuntimeError("Alor circuit breaker open")

    async def get_accounts(self) -> list[BrokerAccount]:
        data = await self._request("GET", "/md/v2/client/profile")
        return [
            BrokerAccount(
                id=str(data.get("portfolio", "")),
                name=data.get("name", ""),
                type=data.get("type", "alor"),
                status="active",
            )
        ]

    async def get_portfolio(self, account_id: str) -> list[BrokerPosition]:
        data = await self._request("GET", f"/md/v2/client/portfolio/{account_id}")
        positions = []
        for p in data.get("positions", []):
            positions.append(
                BrokerPosition(
                    figi=p.get("figi", ""),
                    ticker=p.get("ticker", ""),
                    instrument_type=p.get("instrumentType", ""),
                    quantity=float(p.get("qty", 0)),
                    average_price=float(p.get("avgPrice", 0)),
                    current_price=float(p.get("lastPrice", 0)),
                )
            )
        return positions

    async def get_account_balance(self, account_id: str) -> float:
        data = await self._request("GET", f"/md/v2/client/portfolio/{account_id}")
        return float(data.get("money", 0))

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
        order_params: dict[str, Any] = {
            "figi": figi,
            "quantity": quantity,
            "side": side,
            "type": order_type.value,
        }
        if price is not None:
            order_params["price"] = str(price)
        if time_in_force != TimeInForce.DAY:
            order_params["timeInForce"] = time_in_force.value
        data = await self._request(
            "POST",
            f"/md/v2/client/orders/{account_id}",
            json=order_params,
        )
        return BrokerOrderResult(
            order_id=str(data.get("orderId", "")),
            figi=figi,
            direction=direction,
            order_type=order_type.value,
            executed_price=float(data.get("price", 0)),
            executed_quantity=int(data.get("quantity", 0)),
            status=str(data.get("status", "submitted")),
            idempotency_key=idempotency_key or "",
        )

    async def cancel_order(self, account_id: str, order_id: str) -> bool:
        try:
            await self._request("DELETE", f"/md/v2/client/orders/{account_id}/{order_id}")
            return True
        except Exception as e:
            logger.warning("Alor cancel_order failed: %s", e)
            return False

    async def get_orderbook(self, figi: str, depth: int = 10) -> Optional[dict[str, Any]]:
        return await self._request("GET", f"/md/v2/orderbook/{figi}?depth={depth}")

    async def get_instruments(self, instrument_type: str = "share") -> list[dict[str, Any]]:
        data = await self._request("GET", f"/md/v2/securities?type={instrument_type}&limit=100")
        return data if isinstance(data, list) else []

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
            f"/md/v2/md/{figi}/candles",
            params={
                "from": from_ts.isoformat(),
                "to": now.isoformat(),
                "interval": interval,
            },
        )
        return data if isinstance(data, list) else []


register_broker("alor", AlorClient)
