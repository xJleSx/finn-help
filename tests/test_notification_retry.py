from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import pytest

from src.notifications.retry import ReceiptManager, retry_sync
from src.db.models import NotificationReceipt


@pytest.fixture(autouse=True)
def _clean_notification_receipts(db_session):
    db_session.query(NotificationReceipt).delete()
    db_session.commit()


class TestRetrySync:
    def test_success_first_attempt(self):
        mock = MagicMock()
        decorated = retry_sync(max_attempts=3)(mock)
        decorated()
        assert mock.call_count == 1

    def test_retries_on_failure_then_succeeds(self):
        mock = MagicMock(side_effect=[ValueError("fail"), "ok"])
        decorated = retry_sync(max_attempts=3, base_delay=0.01, backoff=1.0, jitter=False)(mock)
        result = decorated()
        assert result == "ok"
        assert mock.call_count == 2

    def test_raises_after_max_retries(self):
        mock = MagicMock(side_effect=ValueError("always fail"))
        decorated = retry_sync(max_attempts=3, base_delay=0.01, backoff=1.0, jitter=False)(mock)
        with pytest.raises(ValueError, match="always fail"):
            decorated()
        assert mock.call_count == 3

    def test_respects_exception_types(self):
        mock = MagicMock(side_effect=TypeError("wrong type"))
        decorated = retry_sync(max_attempts=3, base_delay=0.01, exceptions=(ValueError,))(mock)
        with pytest.raises(TypeError):
            decorated()
        assert mock.call_count == 1


class TestReceiptManager:
    def test_create_receipt(self, db_session):
        mgr = ReceiptManager(db_session)
        receipt = mgr.create_receipt(
            user_id=1, channel="telegram",
            notification_type="alert", title="Test", message="Hello",
        )
        assert receipt.id is not None
        assert receipt.status == "pending"
        assert receipt.channel == "telegram"

    def test_mark_sent(self, db_session):
        mgr = ReceiptManager(db_session)
        receipt = mgr.create_receipt(user_id=1, channel="email")
        mgr.mark_sent(receipt.id)
        db_session.refresh(receipt)
        assert receipt.status == "sent"
        assert receipt.delivered_at is not None

    def test_mark_failed_with_retry(self, db_session):
        mgr = ReceiptManager(db_session)
        receipt = mgr.create_receipt(user_id=1, channel="telegram", max_retries=3)
        mgr.mark_failed(receipt.id, "connection error")
        db_session.refresh(receipt)
        assert receipt.status == "pending"
        assert receipt.retry_count == 1
        assert receipt.last_error == "connection error"
        assert receipt.next_retry_at is not None

    def test_mark_failed_exhausts_retries(self, db_session):
        mgr = ReceiptManager(db_session)
        receipt = mgr.create_receipt(user_id=1, channel="telegram", max_retries=1)
        mgr.mark_failed(receipt.id, "error 1")
        db_session.refresh(receipt)
        mgr.mark_failed(receipt.id, "error 2")
        db_session.refresh(receipt)
        assert receipt.status == "failed"
        assert receipt.retry_count == 2
        assert receipt.next_retry_at is None

    def test_get_pending_retries(self, db_session):
        mgr = ReceiptManager(db_session)
        r1 = mgr.create_receipt(user_id=1, channel="telegram", max_retries=3)
        r1.status = "pending"
        r1.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        r2 = mgr.create_receipt(user_id=2, channel="email", max_retries=3)
        r2.status = "pending"
        r2.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()
        pending = mgr.get_pending_retries()
        assert len(pending) == 2

    def test_get_pending_retries_future_time(self, db_session):
        mgr = ReceiptManager(db_session)
        receipt = mgr.create_receipt(user_id=1, channel="telegram")
        receipt.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db_session.commit()
        pending = mgr.get_pending_retries()
        assert len(pending) == 0

    def test_get_receipts_by_user(self, db_session):
        mgr = ReceiptManager(db_session)
        mgr.create_receipt(user_id=1, channel="telegram")
        mgr.create_receipt(user_id=2, channel="email")
        receipts = mgr.get_receipts(user_id=1)
        assert len(receipts) == 1
        assert receipts[0].user_id == 1

    def test_get_receipts_by_channel(self, db_session):
        mgr = ReceiptManager(db_session)
        mgr.create_receipt(user_id=1, channel="telegram")
        mgr.create_receipt(user_id=1, channel="email")
        receipts = mgr.get_receipts(channel="email")
        assert len(receipts) == 1
        assert receipts[0].channel == "email"

    def test_get_stats(self, db_session):
        mgr = ReceiptManager(db_session)
        r1 = mgr.create_receipt(user_id=1, channel="telegram")
        mgr.mark_sent(r1.id)
        r2 = mgr.create_receipt(user_id=1, channel="email")
        mgr.mark_failed(r2.id, "error")
        stats = mgr.get_stats(user_id=1)
        assert stats["total"] == 2
        assert stats["sent"] == 1
        assert stats["failed"] == 0
        assert stats["pending"] == 1
