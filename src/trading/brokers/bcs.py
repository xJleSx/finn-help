from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from tenacity import (
    AsyncRetrying,
    before_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.core.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    get_circuit_breaker,
)
from src.trading.brokers.base import (
    BrokerOrderResult,
)
from src.trading.brokers.registry import register_broker

logger = logging.getLogger(__name__)

BASE_URL = "https://be.broker.ru"
TOKEN_URL = f"{BASE_URL}/trade-api-keycloak/realms/tradeapi/protocol/openid-connect/token"
PORTFOLIO_URL = f"{BASE_URL}/trade-api-bff-portfolio/api/v1/portfolio"
OPERATIONS_BFF = f"{BASE_URL}/trade-api-bff-operations"
ORDER_PLACE_URL = f"{OPERATIONS_BFF}/api/v1/orders"
ORDER_CANCEL_URL_TPL = f"{OPERATIONS_BFF}/api/v1/orders/{{order_id}}/cancel"
INFORMATION_BFF = f"{BASE_URL}/trade-api-information-service"
MARKET_DATA_BFF = f"{BASE_URL}/trade-api-market-data-connector"
CANDLES_URL = f"{MARKET_DATA_BFF}/api/v1/candles-chart"
ORDER_BOOK_URL = f"{MARKET_DATA_BFF}/api/v1/order-book"
INSTRUMENTS_BY_TYPE_URL = f"{INFORMATION_BFF}/api/v1/instruments/by-type"

_CB_NAMES = {
    "orders": "bcs_orders",
    "market": "bcs_market",
    "accounts": "bcs_accounts",
    "instruments": "bcs_instruments",
}

_CLIENT_IDS = ("trade-api", "trade-api-write", "trade-api-read")


class BcsClient:
    def __init__(self, token: str = "", use_sandbox: bool = True):
        self._refresh_token = token or settings.bcs_refresh_token or os.environ.get("BCS_REFRESH_TOKEN", "")
        if not self._refresh_token:
            raise ValueError("BCS_REFRESH_TOKEN not set in .env, settings, or token argument")
        self._use_sandbox = use_sandbox
        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._circuit_breaker: CircuitBreaker = get_circuit_breaker("bcs")
        self._orders_cb: CircuitBreaker = get_circuit_breaker("bcs_orders")
        self._market_cb: CircuitBreaker = get_circuit_breaker("bcs_market")

    @property
    def name(self) -> str:
        return "bcs"

    async def __aenter__(self) -> "BcsClient":
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with'")
        last_err: Optional[Exception] = None
        for client_id in _CLIENT_IDS:
            try:
                resp = await self._client.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._refresh_token,
                        "client_id": client_id,
                    },
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                last_err = e
                logger.info("token endpoint rejected client_id=%s, trying next", client_id)
        else:
            raise last_err or RuntimeError("token endpoint did not respond")
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + int(data.get("expires_in", 86400))
        return self._access_token

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        params: Optional[dict[str, str]] = None,
    ) -> Any:
        token = await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if not self._client:
            raise RuntimeError("Client not initialized")
        resp = await self._client.request(method, url, json=json_body, params=params, headers=headers)
        if resp.status_code == 401:
            self._access_token = None
            token = await self._ensure_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = await self._client.request(method, url, json=json_body, params=params, headers=headers)
        resp.raise_for_status()
        if not resp.content:
            return None
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            return resp.json()
        text = resp.text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text

    async def _call_with_retry(
        self,
        fn_name: str,
        fn: Any,
        *args: Any,
        circuit_breaker: Optional[CircuitBreaker] = None,
        **kwargs: Any,
    ) -> Any:
        cb = circuit_breaker or self._circuit_breaker

        async def _do_call() -> Any:
            return await fn(*args, **kwargs)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1.0, max=10.0),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError, ConnectionError)),
            before=before_log(logger, logging.DEBUG),
            reraise=True,
        ):
            with attempt:
                try:
                    return await cb.call(_do_call)
                except CircuitBreakerOpenError:
                    logger.warning("bcs.circuit_breaker.open.%s", fn_name)
                    raise
        return None

    async def get_accounts(self) -> list[dict[str, object]]:
        url = PORTFOLIO_URL
        resp = await self._call_with_retry("get_accounts", self._request, "GET", url)
        raw = resp if isinstance(resp, list) else resp.get("records", resp.get("data", [])) if isinstance(resp, dict) else []
        if isinstance(raw, list):
            account_ids = set()
            for r in raw:
                acc = r.get("account")
                if acc:
                    account_ids.add(str(acc))
            accounts = []
            for aid in account_ids:
                accounts.append(
                    {
                        "id": aid,
                        "type": "broker",
                        "name": f"BCS {aid}",
                        "status": "open",
                        "opened_date": None,
                    }
                )
            if account_ids:
                return accounts
        return [{"id": "default", "type": "broker", "name": "BCS Account", "status": "open", "opened_date": None}]

    async def get_portfolio(self, account_id: str) -> list[dict[str, object]]:
        params = {"account": account_id} if account_id and account_id != "default" else None
        resp = await self._call_with_retry("get_portfolio", self._request, "GET", PORTFOLIO_URL, params=params)
        raw = resp if isinstance(resp, list) else resp.get("records", resp.get("data", [])) if isinstance(resp, dict) else []
        if not isinstance(raw, list):
            return []
        seen: set[tuple[str, str, str]] = set()
        positions = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            if r.get("term") != "T0":
                continue
            ticker = r.get("ticker") or r.get("secId") or ""
            class_code = str(r.get("classCode") or "")
            inst_type = str(r.get("instrumentType") or "")
            key = (ticker, class_code, inst_type)
            if key in seen:
                continue
            seen.add(key)
            positions.append(
                {
                    "figi": ticker,
                    "ticker": ticker,
                    "instrument_type": inst_type,
                    "quantity": float(r.get("quantity", 0) or 0),
                    "average_price": self._float(r.get("avgPrice")),
                    "current_price": self._float(r.get("lastPrice") or r.get("price")),
                    "expected_yield": self._float(r.get("expectedYield") or r.get("unrealizedProfit")),
                }
            )
        return positions

    async def get_account_balance(self, account_id: str) -> float:
        params = {"account": account_id} if account_id and account_id != "default" else None
        resp = await self._call_with_retry("get_account_balance", self._request, "GET", PORTFOLIO_URL, params=params)
        raw = resp if isinstance(resp, list) else resp.get("records", resp.get("data", [])) if isinstance(resp, dict) else []
        if not isinstance(raw, list):
            return 0.0
        total = 0.0
        for r in raw:
            if isinstance(r, dict) and r.get("instrumentType") == "CURRENCY":
                total += self._float(r.get("quantity"))
        return total

    async def get_candles(
        self,
        figi: str,
        interval: str = "hour",
        days: int = 30,
    ) -> list[dict[str, object]]:
        now = datetime.now(timezone.utc)
        body = {
            "ticker": figi,
            "classCode": "TQBR",
            "interval": interval,
            "from": (now - timedelta(days=days)).isoformat(),
            "to": now.isoformat(),
        }
        resp = await self._call_with_retry(
            "get_candles",
            self._request,
            "POST",
            CANDLES_URL,
            json_body=body,
            circuit_breaker=self._market_cb,
        )
        raw = resp if isinstance(resp, list) else resp.get("records", resp.get("data", [])) if isinstance(resp, dict) else []
        if not isinstance(raw, list):
            return []
        return [
            {
                "time": c.get("time", c.get("timestamp", "")),
                "open": self._float(c.get("open")),
                "high": self._float(c.get("high")),
                "low": self._float(c.get("low")),
                "close": self._float(c.get("close")),
                "volume": int(c.get("volume", 0) or 0),
            }
            for c in raw
        ]

    async def place_order(
        self,
        figi: str,
        quantity: int,
        direction: str,
        order_type: str = "market",
        price: Optional[float] = None,
        account_id: str = "",
        idempotency_key: Optional[str] = None,
        time_in_force: str = "day",
    ) -> BrokerOrderResult:
        body: dict[str, Any] = {
            "ticker": figi,
            "side": direction.lower(),
            "type": order_type,
            "quantity": quantity,
        }
        if price is not None and order_type in ("limit", "ioc", "fok"):
            body["price"] = price
        if account_id and account_id != "default":
            body["account"] = account_id
        if idempotency_key:
            logger.info("Placing order figi=%s with idempotency_key=%s", figi, idempotency_key)

        async def _post_order() -> Any:
            return await self._request("POST", ORDER_PLACE_URL, json_body=body)

        resp = await self._call_with_retry(
            "place_order",
            _post_order,
            circuit_breaker=self._orders_cb,
        )
        raw = resp if isinstance(resp, dict) else {}
        result = BrokerOrderResult(
            order_id=str(raw.get("orderId", raw.get("id", ""))),
            figi=figi,
            direction=direction.upper(),
            order_type=order_type,
            executed_price=self._float(raw.get("executedPrice", raw.get("price"))),
            total_commission=self._float(raw.get("commission")),
            executed_quantity=int(raw.get("executedQuantity", raw.get("quantity", 0)) or 0),
            status=str(raw.get("status", raw.get("orderStatus", ""))),
            idempotency_key=idempotency_key or "",
        )
        result.filled_quantity = result.executed_quantity
        result.remaining_quantity = quantity - result.executed_quantity
        return result

    async def cancel_order(self, account_id: str, order_id: str) -> bool:
        url = ORDER_CANCEL_URL_TPL.format(order_id=order_id)
        body: dict[str, Any] = {}
        if account_id and account_id != "default":
            body["account"] = account_id
        try:
            resp = await self._call_with_retry(
                "cancel_order",
                self._request,
                "POST",
                url,
                json_body=body if body else None,
            )
            return resp is not None
        except Exception:
            logger.exception("Unhandled exception")
            return False

    async def get_orderbook(self, figi: str, depth: int = 10) -> Optional[dict[str, object]]:
        body = {"ticker": figi, "classCode": "TQBR", "depth": depth}
        resp = await self._call_with_retry(
            "get_orderbook",
            self._request,
            "POST",
            ORDER_BOOK_URL,
            json_body=body,
            circuit_breaker=self._market_cb,
        )
        raw = resp if isinstance(resp, dict) else {}
        return {
            "figi": figi,
            "bids": [{"price": self._float(b.get("price")), "quantity": b.get("quantity", 0)} for b in raw.get("bids", raw.get("buy", []))],
            "asks": [{"price": self._float(a.get("price")), "quantity": a.get("quantity", 0)} for a in raw.get("asks", raw.get("sell", []))],
        }

    async def get_instruments(self, instrument_type: str = "share") -> list[dict[str, object]]:
        type_map = {
            "share": "SHARE",
            "bond": "BOND",
            "etf": "ETF",
            "currency": "CURRENCY",
        }
        bcs_type = type_map.get(instrument_type, "SHARE")
        url = f"{INSTRUMENTS_BY_TYPE_URL}?type={bcs_type}&page=0&size=100"
        resp = await self._call_with_retry(
            "get_instruments",
            self._request,
            "GET",
            url,
            circuit_breaker=self._market_cb,
        )
        raw = resp if isinstance(resp, list) else resp.get("records", resp.get("data", [])) if isinstance(resp, dict) else []
        if not isinstance(raw, list):
            return []
        return [
            {
                "figi": s.get("ticker", s.get("secId", "")),
                "ticker": s.get("ticker", s.get("secId", "")),
                "name": s.get("name", s.get("shortName", "")),
                "currency": s.get("currency", "RUB"),
                "lot": int(s.get("lot", s.get("lotsize", 1)) or 1),
                "min_price_increment": self._float(s.get("minStep", s.get("minPriceStep", 0.01))),
            }
            for s in raw
        ][:100]

    @staticmethod
    def _float(val: object) -> float:
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0
        return 0.0


register_broker("bcs", BcsClient)
