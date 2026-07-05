"""Tests for broker abstraction layer"""

from __future__ import annotations

from src.trading.brokers.base import (
    BaseBrokerClient,
    BrokerAccount,
    BrokerOrderResult,
    BrokerPosition,
)
from src.trading.brokers.registry import (
    create_broker_client,
    get_broker,
    list_brokers,
    register_broker,
    set_default_broker,
)
from src.trading.types import OrderType, TimeInForce


def test_broker_account_dataclass():
    acc = BrokerAccount(id="acc_1", name="Test", type="sandbox", status="active")
    assert acc.id == "acc_1"
    assert acc.status == "active"


def test_broker_position_dataclass():
    pos = BrokerPosition(figi="BBG001", ticker="SBER", quantity=100, average_price=250)
    assert pos.figi == "BBG001"
    assert pos.quantity == 100


def test_broker_order_result_dataclass():
    result = BrokerOrderResult(
        order_id="ord_123",
        figi="BBG001",
        direction="BUY",
        executed_price=248.5,
        executed_quantity=10,
        status="filled",
    )
    assert result.order_id == "ord_123"
    assert result.status == "filled"
    assert result.executed_price == 248.5


def test_register_and_list_brokers():
    class MockBroker(BaseBrokerClient):
        @property
        def name(self):
            return "mock"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get_accounts(self):
            return []

        async def get_portfolio(self, account_id):
            return []

        async def get_account_balance(self, account_id):
            return 0.0

        async def place_order(
            self,
            figi,
            quantity,
            direction,
            order_type=OrderType.MARKET,
            price=None,
            account_id="",
            idempotency_key=None,
            time_in_force=TimeInForce.DAY,
        ):
            return BrokerOrderResult()

        async def cancel_order(self, account_id, order_id):
            return True

        async def get_orderbook(self, figi, depth=10):
            return None

        async def get_instruments(self, instrument_type="share"):
            return []

        async def get_candles(self, figi, interval="hour", days=30):
            return []

    register_broker("mock", MockBroker)
    assert "mock" in list_brokers()
    assert get_broker("mock") is MockBroker


def test_tbank_broker_registered():
    assert get_broker("tbank") is not None


def test_alor_broker_registered():
    assert get_broker("alor") is not None


def test_finam_broker_registered():
    assert get_broker("finam") is not None


def test_openapi_broker_registered():
    assert get_broker("openapi") is not None


def test_set_default_broker():
    brokers = list_brokers()
    if brokers:
        set_default_broker(brokers[0])
        from src.trading.brokers.registry import get_default_broker

        assert get_default_broker() == brokers[0]


def test_create_broker_client_unknown():
    import pytest

    with pytest.raises(ValueError, match="Unknown broker"):
        create_broker_client(name="nonexistent")
