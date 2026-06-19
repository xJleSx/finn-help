"""Tests for stoploss tracker"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.execution.stoploss import PositionTracker


@pytest.fixture
def tracker():
    with patch.object(PositionTracker, "_restore_from_db"):
        t = PositionTracker()
    return t


class TestPositionTracker:
    def test_init_empty(self, tracker):
        assert tracker._positions == {}

    def test_update_buy_new(self, tracker):
        tracker.update("SBER", "BUY", 10, 250.0)
        assert tracker._positions["SBER"]["shares"] == 10
        assert tracker._positions["SBER"]["avg_price"] == 250.0

    def test_update_buy_add(self, tracker):
        tracker.update("SBER", "BUY", 10, 200.0)
        tracker.update("SBER", "BUY", 10, 300.0)
        assert tracker._positions["SBER"]["shares"] == 20
        assert tracker._positions["SBER"]["avg_price"] == 250.0

    def test_update_sell_partial(self, tracker):
        tracker.update("SBER", "BUY", 10, 250.0)
        tracker.update("SBER", "SELL", 4, 260.0)
        assert tracker._positions["SBER"]["shares"] == 6

    def test_update_sell_all_removes(self, tracker):
        tracker.update("SBER", "BUY", 10, 250.0)
        tracker.update("SBER", "SELL", 10, 260.0)
        assert "SBER" not in tracker._positions

    def test_set_sl_tp(self, tracker):
        with patch.object(tracker, "_persist_sl_tp"):
            tracker.update("SBER", "BUY", 10, 100.0)
            tracker.set_sl_tp("SBER", sl_pct=0.05, tp_pct=0.10)
            assert tracker._positions["SBER"]["sl"] == 95.0
            assert tracker._positions["SBER"]["tp"] == pytest.approx(110.0)

    def test_set_sl_tp_unknown_ticker(self, tracker):
        tracker.set_sl_tp("NONEXISTENT", sl_pct=0.05)
        assert "NONEXISTENT" not in tracker._positions

    def test_check_triggers_no_position(self, tracker):
        assert tracker.check_triggers("NONEXISTENT", 100.0) is None

    def test_check_triggers_stop_loss(self, tracker):
        with patch.object(tracker, "_persist_sl_tp"):
            tracker.update("SBER", "BUY", 10, 100.0)
            tracker.set_sl_tp("SBER", sl_pct=0.05)
            trigger = tracker.check_triggers("SBER", 94.0)
            assert trigger == "stop_loss"

    def test_check_triggers_take_profit(self, tracker):
        with patch.object(tracker, "_persist_sl_tp"):
            tracker.update("SBER", "BUY", 10, 100.0)
            tracker.set_sl_tp("SBER", tp_pct=0.10)
            trigger = tracker.check_triggers("SBER", 111.0)
            assert trigger == "take_profit"

    def test_check_triggers_no_trigger(self, tracker):
        with patch.object(tracker, "_persist_sl_tp"):
            tracker.update("SBER", "BUY", 10, 100.0)
            tracker.set_sl_tp("SBER", sl_pct=0.05, tp_pct=0.10)
            assert tracker.check_triggers("SBER", 100.0) is None

    @pytest.mark.asyncio
    async def test_execute_triggers_calls_sell(self, tracker):
        with (
            patch.object(tracker, "_persist_sl_tp"),
            patch("src.trading.execution.engine.execute_order", new_callable=AsyncMock) as mock_exec,
        ):
            tracker.update("SBER", "BUY", 10, 100.0)
            tracker.set_sl_tp("SBER", sl_pct=0.05)
            result = await tracker.execute_triggers("SBER", 94.0)
            assert result == "stop_loss"
            mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_triggers_no_trigger(self, tracker):
        result = await tracker.execute_triggers("SBER", 100.0)
        assert result is None

    def test_check_triggers_zero_shares(self, tracker):
        tracker._positions["EMPTY"] = {"shares": 0, "avg_price": 0.0, "sl": None, "tp": None}
        assert tracker.check_triggers("EMPTY", 100.0) is None


class TestPositionTrackerRestoreFromDb:
    def test_restore_from_db(self):
        mock_db = MagicMock()
        mock_order = MagicMock()
        mock_order.ticker = "SBER"
        mock_order.quantity = 10
        mock_order.price = 250.0
        mock_order.stop_loss = 237.5
        mock_order.take_profit = 275.0
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_order]

        with patch("src.trading.execution.stoploss.get_session", return_value=mock_db):
            tracker = PositionTracker()
            assert "SBER" in tracker._positions
            assert tracker._positions["SBER"]["shares"] == 10

    def test_restore_from_db_exception(self):
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("DB error")

        with patch("src.trading.execution.stoploss.get_session", return_value=mock_db):
            tracker = PositionTracker()
            assert tracker._positions == {}
