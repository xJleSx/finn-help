"""Tests for stoploss position tracker"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.execution.stoploss import PositionTracker


@pytest.fixture
def tracker():
    with patch.object(PositionTracker, "_restore_from_db", return_value=None):
        t = PositionTracker()
        t._positions = {}
        return t


def test_update_buy(tracker):
    tracker.update("SBER", "BUY", 10, 250.0)
    assert tracker._positions["SBER"]["shares"] == 10
    assert tracker._positions["SBER"]["avg_price"] == 250.0

    tracker.update("SBER", "BUY", 5, 260.0)
    assert tracker._positions["SBER"]["shares"] == 15
    expected_avg = (250.0 * 10 + 260.0 * 5) / 15
    assert tracker._positions["SBER"]["avg_price"] == expected_avg


def test_update_sell(tracker):
    tracker.update("GAZP", "BUY", 20, 150.0)
    tracker.update("GAZP", "SELL", 5, 160.0)
    assert tracker._positions["GAZP"]["shares"] == 15

    tracker.update("GAZP", "SELL", 15, 170.0)
    assert "GAZP" not in tracker._positions


def test_set_sl_tp(tracker):
    tracker.update("SBER", "BUY", 10, 250.0)
    tracker.set_sl_tp("SBER", sl_pct=0.05, tp_pct=0.10)

    pos = tracker._positions["SBER"]
    assert pos["sl"] == 250.0 * (1 - 0.05)
    assert pos["tp"] == 250.0 * (1 + 0.10)


def test_check_triggers_stop_loss(tracker):
    tracker.update("SBER", "BUY", 10, 250.0)
    tracker.set_sl_tp("SBER", sl_pct=0.05)

    result = tracker.check_triggers("SBER", 230.0)
    assert result == "stop_loss"

    result = tracker.check_triggers("SBER", 240.0)
    assert result is None

    result = tracker.check_triggers("SBER", 237.5)
    assert result == "stop_loss"


def test_check_triggers_take_profit(tracker):
    tracker.update("SBER", "BUY", 10, 250.0)
    tracker.set_sl_tp("SBER", tp_pct=0.10)

    result = tracker.check_triggers("SBER", 280.0)
    assert result == "take_profit"

    result = tracker.check_triggers("SBER", 270.0)
    assert result is None


def test_check_triggers_no_position(tracker):
    result = tracker.check_triggers("NONEXISTENT", 100.0)
    assert result is None


def test_check_triggers_zero_shares(tracker):
    tracker._positions["EMPTY"] = {"shares": 0, "avg_price": 0.0, "sl": None, "tp": None}
    result = tracker.check_triggers("EMPTY", 100.0)
    assert result is None


@pytest.mark.asyncio
async def test_execute_triggers(tracker):
    tracker.update("SBER", "BUY", 10, 250.0)
    tracker.set_sl_tp("SBER", sl_pct=0.05)

    with patch("src.trading.execution.engine.execute_order", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = MagicMock()
        mock_exec.return_value.status = "filled"

        result = await tracker.execute_triggers("SBER", 230.0)
        assert result == "stop_loss"
        mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_execute_triggers_no_trigger(tracker):
    tracker.update("SBER", "BUY", 10, 250.0)
    tracker.set_sl_tp("SBER", sl_pct=0.05)

    with patch("src.trading.execution.engine.execute_order") as mock_exec:
        result = await tracker.execute_triggers("SBER", 250.0)
        assert result is None
        mock_exec.assert_not_called()


def test_persist_sl_tp(tracker):
    tracker.update("SBER", "BUY", 10, 250.0)
    tracker.set_sl_tp("SBER", sl_pct=0.05)

    import src.trading.execution.stoploss as sl
    original = sl.get_session
    try:
        sl.get_session = MagicMock()
        mock_get_session = sl.get_session
        mock_db = MagicMock()
        mock_order = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_order]
        mock_get_session.return_value = mock_db

        tracker._persist_sl_tp("SBER")
        assert mock_order.stop_loss == tracker._positions["SBER"]["sl"]
        mock_db.commit.assert_called_once()
    finally:
        sl.get_session = original


def test_restore_from_db():
    import src.trading.execution.stoploss as sl
    original = sl.get_session
    try:
        sl.get_session = MagicMock()
        mock_db = MagicMock()
        mock_order = MagicMock()
        mock_order.ticker = "RESTORED"
        mock_order.quantity = 10
        mock_order.price = 200.0
        mock_order.stop_loss = 190.0
        mock_order.take_profit = 220.0

        mock_db.query.return_value.filter.return_value.all.return_value = [mock_order]
        sl.get_session.return_value = mock_db

        t = PositionTracker.__new__(PositionTracker)
        t._positions = {}
        t._restore_from_db()
        assert "RESTORED" in t._positions
        assert t._positions["RESTORED"]["shares"] == 10
        assert t._positions["RESTORED"]["avg_price"] == 200.0
        assert t._positions["RESTORED"]["sl"] == 190.0
        assert t._positions["RESTORED"]["tp"] == 220.0
    finally:
        sl.get_session = original
