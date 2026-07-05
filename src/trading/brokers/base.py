from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from src.trading.types import OrderType, TimeInForce


@dataclass
class BrokerOrderResult:
    order_id: str = ""
    figi: str = ""
    direction: str = ""
    order_type: str = "market"
    executed_price: float = 0.0
    executed_quantity: int = 0
    total_commission: float = 0.0
    status: str = ""
    filled_quantity: int = 0
    remaining_quantity: int = 0
    idempotency_key: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerPosition:
    figi: str = ""
    ticker: str = ""
    instrument_type: str = ""
    quantity: float = 0.0
    average_price: float = 0.0
    current_price: float = 0.0
    expected_yield: float = 0.0


@dataclass
class BrokerAccount:
    id: str = ""
    name: str = ""
    type: str = ""
    status: str = ""
    opened_date: str = ""


class BaseBrokerClient(ABC):
    def __init__(self, token: str = "", use_sandbox: bool = True):
        self._token = token
        self._use_sandbox = use_sandbox

    @abstractmethod
    async def __aenter__(self) -> BaseBrokerClient: ...

    @abstractmethod
    async def __aexit__(self, *args: object) -> None: ...

    @abstractmethod
    async def get_accounts(self) -> list[BrokerAccount]: ...

    @abstractmethod
    async def get_portfolio(self, account_id: str) -> list[BrokerPosition]: ...

    @abstractmethod
    async def get_account_balance(self, account_id: str) -> float: ...

    @abstractmethod
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
    ) -> BrokerOrderResult: ...

    @abstractmethod
    async def cancel_order(self, account_id: str, order_id: str) -> bool: ...

    @abstractmethod
    async def get_orderbook(self, figi: str, depth: int = 10) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    async def get_instruments(self, instrument_type: str = "share") -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_candles(
        self,
        figi: str,
        interval: str = "hour",
        days: int = 30,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def name(self) -> str: ...
