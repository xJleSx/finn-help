"""Tests for execution engine"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.execution.engine import (
    TradeMode,
    cancel_pending,
    execute_order,
    get_log,
    get_mode,
    set_mode,
)


@pytest.fixture(autouse=True)
def reset_engine():
    import src.trading.execution.engine as eng

    async def _reset():
        async with eng._mode_lock:
            eng._mode = TradeMode.MANUAL
            eng._execution_log.clear()

    import asyncio

    asyncio.run(_reset())
    yield


@pytest.mark.asyncio
async def test_set_and_get_mode():
    await set_mode(TradeMode.DRY_RUN)
    assert get_mode() == TradeMode.DRY_RUN

    await set_mode(TradeMode.AUTO)
    assert get_mode() == TradeMode.AUTO

    await set_mode(TradeMode.MANUAL)
    assert get_mode() == TradeMode.MANUAL


@pytest.mark.asyncio
async def test_execute_dry_run():
    await set_mode(TradeMode.DRY_RUN)
    record = await execute_order(
        ticker="SBER",
        direction="BUY",
        quantity=10,
        price=250.0,
        reason="test_dry_run",
    )
    assert record.status == "simulated"
    assert record.order_id is not None
    assert record.order_id.startswith("dry_")

    log = get_log(limit=5)
    assert len(log) >= 1
    assert log[-1]["ticker"] == "SBER"
    assert log[-1]["direction"] == "BUY"


@pytest.mark.asyncio
async def test_execute_manual():
    await set_mode(TradeMode.MANUAL)
    record = await execute_order(
        ticker="GAZP",
        direction="SELL",
        quantity=5,
        price=150.0,
        reason="test_manual",
    )
    assert record.status == "pending_approval"


@pytest.mark.asyncio
@patch("src.trading.execution.engine.settings")
async def test_execute_auto_no_token(mock_settings):
    mock_settings.tinkoff_token = ""
    await set_mode(TradeMode.AUTO)
    record = await execute_order(
        ticker="SBER",
        direction="BUY",
        quantity=10,
        price=250.0,
        reason="test_auto_no_token",
    )
    assert record.status == "failed"


@pytest.mark.asyncio
@patch("src.trading.execution.engine.settings")
@patch("src.trading.execution.engine.TBankClient")
async def test_execute_auto_success(mock_tbank, mock_settings):
    mock_settings.tinkoff_token = "test_token"
    mock_settings.tinkoff_sandbox = True
    mock_settings.enable_trading = True

    mock_client = AsyncMock()
    mock_client.get_accounts = AsyncMock(return_value=[{"id": "acc_1"}])
    mock_client.place_order = AsyncMock(
        return_value={
            "order_id": "ord_123",
            "status": "filled",
            "executed_quantity": 5,
            "executed_price": 248.0,
        }
    )
    mock_tbank.return_value.__aenter__.return_value = mock_client

    import src.trading.execution.engine as eng

    async def _set():
        async with eng._mode_lock:
            eng._mode = TradeMode.AUTO

    await _set()

    with (
        patch("src.db.connection.get_session") as mock_get_session,
        patch("src.trading.execution.engine.personal", {"execution": {"delay_ms": 0}}),
    ):
        mock_db = MagicMock()
        mock_inst = MagicMock()
        mock_inst.figi = "BBG000000001"
        mock_inst.lot_size = 1
        mock_inst.id = 1
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_inst
        mock_get_session.return_value = mock_db

        record = await execute_order(
            ticker="SBER",
            direction="BUY",
            quantity=5,
            price=250.0,
            figi="BBG000000001",
            reason="test_auto",
        )
        assert record.order_id == "ord_123"
        assert record.status == "filled"


@pytest.mark.asyncio
@patch("src.trading.execution.engine.settings")
async def test_execute_auto_trading_disabled(mock_settings):
    mock_settings.enable_trading = False
    mock_settings.tinkoff_token = "test_token"
    await set_mode(TradeMode.AUTO)
    record = await execute_order(
        ticker="SBER",
        direction="BUY",
        quantity=10,
        price=250.0,
        reason="test_disabled",
    )
    assert record.status == "failed"


@pytest.mark.asyncio
@patch("src.trading.execution.engine.settings")
@patch("src.trading.execution.engine.TBankClient")
async def test_execute_auto_no_figi(mock_tbank, mock_settings):
    mock_settings.enable_trading = True
    mock_settings.tinkoff_token = "test_token"
    mock_settings.tinkoff_sandbox = True

    import src.trading.execution.engine as eng

    async def _set():
        async with eng._mode_lock:
            eng._mode = TradeMode.AUTO

    await _set()

    with (
        patch("src.db.connection.get_session") as mock_get_session,
        patch("src.trading.execution.engine.personal", {"execution": {"delay_ms": 0}}),
    ):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        mock_get_session.return_value = mock_db

        record = await execute_order(
            ticker="SBER",
            direction="BUY",
            quantity=5,
            price=250.0,
            reason="test_no_figi",
        )
        assert record.status == "failed"


@pytest.mark.asyncio
@patch("src.trading.execution.engine.settings")
@patch("src.trading.execution.engine.TBankClient")
async def test_execute_auto_quantity_less_than_lot(mock_tbank, mock_settings):
    mock_settings.enable_trading = True
    mock_settings.tinkoff_token = "test_token"
    mock_settings.tinkoff_sandbox = True

    import src.trading.execution.engine as eng

    async def _set():
        async with eng._mode_lock:
            eng._mode = TradeMode.AUTO

    await _set()

    with (
        patch("src.db.connection.get_session") as mock_get_session,
        patch("src.trading.execution.engine.personal", {"execution": {"delay_ms": 0}}),
    ):
        mock_db = MagicMock()
        mock_inst = MagicMock()
        mock_inst.figi = "BBG000000001"
        mock_inst.lot_size = 10
        mock_inst.id = 1
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_inst
        mock_get_session.return_value = mock_db

        record = await execute_order(
            ticker="SBER",
            direction="BUY",
            quantity=5,
            price=250.0,
            figi="BBG000000001",
            reason="test_small_qty",
        )
        assert record.status == "failed"


@pytest.mark.asyncio
async def test_approve_order_trading_disabled():
    from src.trading.execution.engine import approve_order

    with patch("src.trading.execution.engine.settings.enable_trading", False):
        result = await approve_order(ticker="VTBR", direction="BUY", quantity=20)
        assert result is None


@pytest.mark.asyncio
async def test_approve_order():
    import src.trading.execution.engine as eng
    from src.trading.execution.engine import approve_order

    r = eng.OrderRecord(ticker="VTBR", direction="BUY", quantity=20, price=0.05, mode=TradeMode.MANUAL)
    r.status = "pending_approval"
    eng._execution_log.append(r)

    with (
        patch("src.trading.execution.engine.settings.enable_trading", True),
        patch("src.trading.execution.engine.execute_order", new_callable=AsyncMock) as mock_exec,
        patch("src.db.connection.get_session") as mock_get_session,
    ):
        fake_record = MagicMock()
        fake_record.status = "filled"
        mock_exec.return_value = fake_record
        mock_db = MagicMock()
        mock_get_session.return_value = mock_db

        result = await approve_order(ticker="VTBR", direction="BUY", quantity=20)
        assert result is not None
        assert result.status == "filled"


@pytest.mark.asyncio
async def test_cancel_pending():
    import src.trading.execution.engine as eng

    r = eng.OrderRecord(ticker="TEST", direction="BUY", quantity=1, price=100, mode=TradeMode.MANUAL)
    r.status = "pending_approval"
    eng._execution_log.append(r)

    result = await cancel_pending("TEST")
    assert result is True

    assert r.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_pending_already_approved():
    import src.trading.execution.engine as eng

    r = eng.OrderRecord(ticker="TEST", direction="BUY", quantity=1, price=100, mode=TradeMode.MANUAL)
    r.status = "filled"
    eng._execution_log.append(r)

    result = await cancel_pending("TEST")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_pending_not_found():
    result = await cancel_pending("NONEXISTENT")
    assert result is False


@pytest.mark.asyncio
async def test_get_log():
    await set_mode(TradeMode.DRY_RUN)
    await execute_order(ticker="A", direction="BUY", quantity=1, price=10, reason="log_test")
    await execute_order(ticker="B", direction="SELL", quantity=2, price=20, reason="log_test")

    log = get_log(limit=10)
    assert len(log) >= 2
    assert log[-1]["ticker"] == "B"
    assert log[-2]["ticker"] == "A"


@pytest.mark.asyncio
@patch("src.trading.execution.engine.settings")
@patch("src.trading.execution.engine.TBankClient")
async def test_execute_auto_no_accounts(mock_tbank, mock_settings):
    mock_settings.enable_trading = True
    mock_settings.tinkoff_token = "test_token"
    mock_settings.tinkoff_sandbox = True

    mock_client = AsyncMock()
    mock_client.get_accounts = AsyncMock(return_value=[])
    mock_tbank.return_value.__aenter__.return_value = mock_client

    import src.trading.execution.engine as eng

    async def _set():
        async with eng._mode_lock:
            eng._mode = TradeMode.AUTO

    await _set()

    with (
        patch("src.db.connection.get_session") as mock_get_session,
        patch("src.trading.execution.engine.personal", {"execution": {"delay_ms": 0}}),
    ):
        mock_db = MagicMock()
        mock_inst = MagicMock()
        mock_inst.figi = "BBG000000001"
        mock_inst.lot_size = 1
        mock_inst.id = 1
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_inst
        mock_get_session.return_value = mock_db

        record = await execute_order(
            ticker="SBER",
            direction="BUY",
            quantity=5,
            price=250.0,
            figi="BBG000000001",
            reason="test_no_accounts",
        )
        assert record.status == "failed"


@pytest.mark.asyncio
@patch("src.trading.execution.engine.settings")
@patch("src.trading.execution.engine.TBankClient")
async def test_execute_auto_exception(mock_tbank, mock_settings):
    mock_settings.enable_trading = True
    mock_settings.tinkoff_token = "test_token"
    mock_settings.tinkoff_sandbox = True

    mock_client = AsyncMock()
    mock_client.get_accounts = AsyncMock(side_effect=Exception("API error"))
    mock_tbank.return_value.__aenter__.return_value = mock_client

    import src.trading.execution.engine as eng

    async def _set():
        async with eng._mode_lock:
            eng._mode = TradeMode.AUTO

    await _set()

    with (
        patch("src.db.connection.get_session") as mock_get_session,
        patch("src.trading.execution.engine.personal", {"execution": {"delay_ms": 0}}),
    ):
        mock_db = MagicMock()
        mock_inst = MagicMock()
        mock_inst.figi = "BBG000000001"
        mock_inst.lot_size = 1
        mock_inst.id = 1
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_inst
        mock_get_session.return_value = mock_db

        record = await execute_order(
            ticker="SBER",
            direction="BUY",
            quantity=5,
            price=250.0,
            figi="BBG000000001",
            reason="test_exception",
        )
        assert record.status == "failed"


def test_notify_trade_calls_broadcast():
    import sys
    from unittest.mock import MagicMock, patch

    import src.trading.execution.engine as eng

    mock_telegram = MagicMock()
    sys.modules["src.interfaces.telegram"] = mock_telegram

    record = eng.OrderRecord(ticker="TEST", direction="BUY", quantity=1, price=100, mode=TradeMode.DRY_RUN)
    with patch("src.trading.execution.engine.asyncio.ensure_future") as mock_future:
        eng._notify_trade(record, reason="test")
        mock_future.assert_called_once()
