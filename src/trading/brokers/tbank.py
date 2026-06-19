import logging
from datetime import datetime, timedelta, timezone

from typing import Optional

from src.config import settings

logger = logging.getLogger(__name__)

try:
    from t_tech.invest import (
        AsyncClient,
        CandleInterval,
        InstrumentType,
        OrderDirection,
        OrderType,
    )
    from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX

    HAS_SDK = True
except ImportError:
    HAS_SDK = False
    logger.warning("t-tech-investments SDK not installed. Install with: uv pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple")

SANDBOX_TARGET = "sandbox"  # sandbox target identifier


class TBankClient:
    def __init__(self, use_sandbox: bool = True):
        self._token = settings.tinkoff_token
        if not self._token:
            raise ValueError("TINKOFF_TOKEN not set in .env")
        self._use_sandbox = use_sandbox
        self._client: Optional[AsyncClient] = None
        self._raw_client: Optional[AsyncClient] = None

    def _target(self) -> str:
        return INVEST_GRPC_API_SANDBOX if self._use_sandbox else INVEST_GRPC_API

    async def __aenter__(self) -> "TBankClient":
        self._raw_client = AsyncClient(self._token, target=self._target())
        self._client = await self._raw_client.__aenter__()  # type: ignore[assignment]
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._raw_client:
            await self._raw_client.__aexit__(*args)  # type: ignore[no-untyped-call]
            self._client = None
            self._raw_client = None

    async def get_accounts(self) -> list[dict[str, object]]:
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with'")
        resp = await self._client.users.get_accounts()  # type: ignore[attr-defined]
        return [
            {
                "id": a.id,
                "type": a.type,
                "name": a.name,
                "status": a.status,
                "opened_date": str(a.opened_date) if a.opened_date else None,
            }
            for a in resp.accounts
        ]

    async def get_portfolio(self, account_id: str) -> list[dict[str, object]]:
        if not self._client:
            raise RuntimeError("Client not initialized")
        resp = await self._client.operations.get_portfolio(account_id=account_id)  # type: ignore[attr-defined]
        positions = []
        for p in resp.positions:
            if p.instrument_type in ("share", "etf", "bond"):
                positions.append(
                    {
                        "figi": p.figi,
                        "ticker": p.instrument_uid,
                        "quantity": self._decimal(p.quantity),
                        "average_price": self._money(p.average_position_price),
                        "current_price": self._money(p.current_price),
                        "expected_yield": self._money(p.expected_yield),
                    }
                )
        return positions

    async def get_account_balance(self, account_id: str) -> float:
        if not self._client:
            raise RuntimeError("Client not initialized")
        resp = await self._client.operations.get_portfolio(account_id=account_id)  # type: ignore[attr-defined]
        total = 0.0
        for p in resp.positions:
            if p.instrument_type == "currency":
                total += self._money(p.quantity)
        return total

    async def get_candles(
        self,
        figi: str,
        interval: str = "hour",
        days: int = 30,
    ) -> list[dict[str, object]]:
        if not self._client:
            raise RuntimeError("Client not initialized")
        interval_map = {
            "1min": CandleInterval.CANDLE_INTERVAL_1_MIN,
            "5min": CandleInterval.CANDLE_INTERVAL_5_MIN,
            "15min": CandleInterval.CANDLE_INTERVAL_15_MIN,
            "hour": CandleInterval.CANDLE_INTERVAL_HOUR,
            "day": CandleInterval.CANDLE_INTERVAL_DAY,
        }
        ci = interval_map.get(interval, CandleInterval.CANDLE_INTERVAL_HOUR)
        now = datetime.now(timezone.utc)
        resp = await self._client.market_data.get_candles(  # type: ignore[attr-defined]
            figi=figi,
            from_=now - timedelta(days=days),
            to=now,
            interval=ci,
        )
        return [
            {
                "time": c.time.isoformat(),
                "open": self._decimal(c.open),
                "high": self._decimal(c.high),
                "low": self._decimal(c.low),
                "close": self._decimal(c.close),
                "volume": c.volume,
            }
            for c in resp.candles
        ]

    async def place_order(
        self,
        figi: str,
        quantity: int,
        direction: str,  # BUY or SELL
        order_type: str = "market",  # market or limit
        price: Optional[float] = None,
        account_id: str = "",
    ) -> dict[str, object]:
        if not self._client:
            raise RuntimeError("Client not initialized")
        direction_enum = OrderDirection.ORDER_DIRECTION_BUY if direction.upper() == "BUY" else OrderDirection.ORDER_DIRECTION_SELL
        type_enum = OrderType.ORDER_TYPE_MARKET if order_type == "market" else OrderType.ORDER_TYPE_LIMIT
        price_quotation = None
        if price is not None:
            price_quotation = self._to_quotation(price)

        resp = await self._client.orders.post_order(  # type: ignore[attr-defined]
            figi=figi,
            quantity=quantity,
            direction=direction_enum,
            order_type=type_enum,
            price=price_quotation,
            account_id=account_id,
        )
        return {
            "order_id": resp.order_id,
            "figi": resp.figi,
            "direction": "BUY" if resp.direction == 1 else "SELL",
            "type": "market" if resp.order_type == 1 else "limit",
            "executed_price": self._money(resp.executed_order_price),
            "total_commission": self._money(resp.executed_commission),
            "executed_quantity": resp.lots_executed,
            "status": str(resp.execution_report_status),
        }

    async def sandbox_pay_in(self, account_id: str, amount: float, currency: str = "RUB") -> dict[str, object]:
        if not self._client:
            raise RuntimeError("Client not initialized")
        from t_tech.invest.grpc.sandbox_pb2 import SandboxPayInRequest as ProtoRequest

        req = ProtoRequest()
        req.account_id = account_id
        req.amount.units = int(amount)
        req.amount.nano = int(round((amount - int(amount)) * 1e9))
        req.amount.currency = currency
        resp = await self._client.sandbox.stub.SandboxPayIn(  # type: ignore[attr-defined]
            request=req, metadata=self._client.sandbox.metadata  # type: ignore[attr-defined]
        )
        return {"units": resp.balance.units, "nano": resp.balance.nano, "currency": resp.balance.currency}

    async def cancel_order(self, account_id: str, order_id: str) -> bool:
        if not self._client:
            raise RuntimeError("Client not initialized")
        resp = await self._client.orders.cancel_order(account_id=account_id, order_id=order_id)  # type: ignore[attr-defined]
        return resp.time is not None

    async def get_orderbook(self, figi: str, depth: int = 10) -> Optional[dict[str, object]]:
        if not self._client:
            raise RuntimeError("Client not initialized")
        resp = await self._client.market_data.get_order_book(figi=figi, depth=depth)  # type: ignore[attr-defined]
        return {
            "figi": resp.figi,
            "bids": [{"price": self._money(b.price), "quantity": b.quantity} for b in resp.bids],
            "asks": [{"price": self._money(a.price), "quantity": a.quantity} for a in resp.asks],
        }

    async def get_instruments(self, instrument_type: str = "share") -> list[dict[str, object]]:
        if not self._client:
            raise RuntimeError("Client not initialized")
        type_map = {
            "share": InstrumentType.INSTRUMENT_TYPE_SHARE,
            "bond": InstrumentType.INSTRUMENT_TYPE_BOND,
            "etf": InstrumentType.INSTRUMENT_TYPE_ETF,
            "currency": InstrumentType.INSTRUMENT_TYPE_CURRENCY,
        }
        it = type_map.get(instrument_type, InstrumentType.INSTRUMENT_TYPE_SHARE)
        resp = await self._client.instruments.shares() if it == InstrumentType.INSTRUMENT_TYPE_SHARE else await self._client.instruments.instruments(instrument_type=it)  # type: ignore[attr-defined]
        return [
            {
                "figi": s.figi,
                "ticker": s.ticker,
                "name": s.name,
                "currency": s.currency,
                "lot": s.lot,
                "min_price_increment": self._decimal(s.min_price_increment),
            }
            for s in resp.instruments[:100]
        ]

    @staticmethod
    def _decimal(val: object) -> float:
        if hasattr(val, "units") and hasattr(val, "nano"):
            return val.units + val.nano / 1e9  # type: ignore[no-any-return]
        if isinstance(val, (int, float)):
            return float(val)
        return 0.0

    @staticmethod
    def _money(val: object) -> float:
        if hasattr(val, "units") and hasattr(val, "nano"):
            return val.units + val.nano / 1e9  # type: ignore[no-any-return]
        return 0.0

    @staticmethod
    def _to_quotation(val: float) -> object:
        from t_tech.invest import Quotation
        units = int(val)
        nano = int(round((val - units) * 1e9))
        return Quotation(units=units, nano=nano)

