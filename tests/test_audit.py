"""Tests for execution audit"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.trading.execution.audit import (
    audit_log_order,
    get_order_history,
    get_trade_history,
    log_trade,
    save_order,
    update_order_status,
)


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.add.return_value = None
    db.commit.return_value = None
    db.rollback.return_value = None
    db.close.return_value = None
    return db


@pytest.fixture
def mock_order_record():
    record = MagicMock()
    record.ticker = "SBER"
    record.direction = "BUY"
    record.quantity = 10
    record.price = 250.0
    record.status = "simulated"
    record.mode.value = "dry_run"
    record.reason = "test"
    record.order_id = "dry_123"
    record.created_at = None
    return record


class TestSaveOrder:
    def test_save_success(self, mock_db, mock_order_record):
        mock_order_model = MagicMock()
        mock_order_model.id = 42

        with (
            patch("src.trading.execution.audit.get_session", return_value=mock_db),
            patch("src.trading.execution.audit.AUDIT_DIR"),
            patch("src.trading.execution.audit.OrderModel", return_value=mock_order_model),
        ):
            result = save_order(mock_order_record)
            assert result == 42

    def test_save_exception(self, mock_db, mock_order_record):
        mock_order_model = MagicMock()
        mock_order_model.id = 42

        with (
            patch("src.trading.execution.audit.get_session", return_value=mock_db),
            patch("src.trading.execution.audit.AUDIT_DIR"),
            patch("src.trading.execution.audit.OrderModel", return_value=mock_order_model),
        ):
            mock_db.add.side_effect = Exception("DB error")
            result = save_order(mock_order_record)
            assert result == 0
            mock_db.rollback.assert_called_once()


class TestLogTrade:
    def test_log_success(self, mock_db):
        with (
            patch("src.trading.execution.audit.get_session", return_value=mock_db),
            patch("src.trading.execution.audit.AUDIT_DIR"),
            patch("src.trading.execution.audit.TradeLog"),
        ):
            log_trade(
                ticker="SBER",
                direction="BUY",
                quantity=10,
                price=250.0,
                commission=1.5,
                slippage=0.001,
                pnl=50.0,
                reason="test",
                order_id=42,
            )
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()

    def test_log_exception(self, mock_db):
        with (
            patch("src.trading.execution.audit.get_session", return_value=mock_db),
            patch("src.trading.execution.audit.AUDIT_DIR"),
            patch("src.trading.execution.audit.TradeLog"),
        ):
            mock_db.add.side_effect = Exception("DB error")
            log_trade(
                ticker="SBER",
                direction="BUY",
                quantity=10,
                price=250.0,
            )
            mock_db.rollback.assert_called_once()


class TestGetTradeHistory:
    def test_returns_list(self, mock_db):
        mock_trade = MagicMock()
        mock_trade.id = 1
        mock_trade.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_trade.ticker = "SBER"
        mock_trade.direction = "BUY"
        mock_trade.quantity = 10
        mock_trade.price = 250.0
        mock_trade.commission = 0.0
        mock_trade.pnl = 0.0
        mock_trade.reason = ""
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_trade]

        with patch("src.trading.execution.audit.get_session", return_value=mock_db):
            result = get_trade_history(limit=5)
            assert len(result) == 1
            assert result[0]["ticker"] == "SBER"

    def test_empty(self, mock_db):
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with patch("src.trading.execution.audit.get_session", return_value=mock_db):
            assert get_trade_history() == []


class TestGetOrderHistory:
    def test_returns_list(self, mock_db):
        mock_order = MagicMock()
        mock_order.id = 1
        mock_order.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_order.ticker = "SBER"
        mock_order.direction = "BUY"
        mock_order.quantity = 10
        mock_order.price = 250.0
        mock_order.status = "filled"
        mock_order.mode = "auto"
        mock_order.reason = ""
        mock_order.order_id_ext = ""
        mock_order.commission = 0.0
        mock_order.executed_price = None
        mock_order.stop_loss = None
        mock_order.take_profit = None
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_order]

        with patch("src.trading.execution.audit.get_session", return_value=mock_db):
            result = get_order_history(limit=5)
            assert len(result) == 1
            assert result[0]["ticker"] == "SBER"


class TestUpdateOrderStatus:
    def test_update_success(self, mock_db):
        class FakeOrder:
            status = "pending"
            executed_price = None

        mock_db.query.return_value.filter_by.return_value.first.return_value = FakeOrder()

        with patch("src.trading.execution.audit.get_session", return_value=mock_db):
            update_order_status(1, "filled", executed_price=248.0)
            mock_db.commit.assert_called_once()

    def test_update_not_found(self, mock_db):
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.trading.execution.audit.get_session", return_value=mock_db):
            update_order_status(999, "cancelled")
            mock_db.commit.assert_not_called()

    def test_update_exception(self, mock_db):
        mock_db.query.return_value.filter_by.return_value.first.side_effect = Exception("DB error")

        with patch("src.trading.execution.audit.get_session", return_value=mock_db):
            update_order_status(1, "filled")
            mock_db.rollback.assert_called_once()


class TestAuditLogOrder:
    def test_writes_jsonl(self):
        with (
            patch("src.trading.execution.audit.AUDIT_DIR"),
            patch("builtins.open") as mock_open,
        ):
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file
            audit_log_order({"event": "test"})
            mock_file.write.assert_called_once()

    def test_write_exception(self):
        with (
            patch("src.trading.execution.audit.AUDIT_DIR"),
            patch("builtins.open") as mock_open,
        ):
            mock_file = MagicMock()
            mock_file.write.side_effect = Exception("IO error")
            mock_open.return_value.__enter__.return_value = mock_file
            audit_log_order({"event": "test"})
