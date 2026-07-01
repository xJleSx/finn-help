from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

from src.db.models import NotificationReceipt

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry_sync(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    backoff: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc = None
            delay = base_delay
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        actual_delay = delay + (random.uniform(0, delay * 0.5) if jitter else 0)
                        logger.warning(
                            "retry_attempt %s/%s failed: %s, retrying in %.1fs",
                            attempt + 1, max_attempts, e, actual_delay,
                        )
                        time.sleep(actual_delay)
                        delay *= backoff
            raise last_exc  # type: ignore
        return wrapper  # type: ignore
    return decorator


def retry_async(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    backoff: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc = None
            delay = base_delay
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        actual_delay = delay + (random.uniform(0, delay * 0.5) if jitter else 0)
                        logger.warning(
                            "retry_attempt %s/%s failed: %s, retrying in %.1fs",
                            attempt + 1, max_attempts, e, actual_delay,
                        )
                        await asyncio.sleep(actual_delay)
                        delay *= backoff
            raise last_exc  # type: ignore
        return wrapper  # type: ignore
    return decorator


class ReceiptManager:
    def __init__(self, db: Any) -> None:
        self._db = db

    def create_receipt(
        self,
        user_id: int,
        channel: str,
        notification_type: str | None = None,
        title: str | None = None,
        message: str | None = None,
        max_retries: int = 3,
    ) -> NotificationReceipt:
        receipt = NotificationReceipt(
            user_id=user_id,
            channel=channel,
            notification_type=notification_type,
            title=title,
            message=message,
            status="pending",
            max_retries=max_retries,
            next_retry_at=datetime.now(timezone.utc),
        )
        self._db.add(receipt)
        self._db.commit()
        return receipt

    def mark_sent(self, receipt_id: int) -> None:
        receipt = self._db.query(NotificationReceipt).filter_by(id=receipt_id).first()
        if receipt:
            receipt.status = "sent"
            receipt.delivered_at = datetime.now(timezone.utc)
            receipt.next_retry_at = None
            self._db.commit()

    def mark_failed(self, receipt_id: int, error: str, schedule_retry: bool = True) -> None:
        receipt = self._db.query(NotificationReceipt).filter_by(id=receipt_id).first()
        if receipt:
            receipt.status = "failed"
            receipt.retry_count = (receipt.retry_count or 0) + 1
            receipt.last_error = error[:500]
            if schedule_retry and receipt.retry_count < receipt.max_retries:
                receipt.status = "pending"
                delay = 2.0 * (2.0 ** (receipt.retry_count - 1))
                receipt.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            else:
                receipt.next_retry_at = None
            self._db.commit()

    def get_pending_retries(self, limit: int = 50) -> list[NotificationReceipt]:
        now = datetime.now(timezone.utc)
        return (
            self._db.query(NotificationReceipt)
            .filter(
                NotificationReceipt.status == "pending",
                NotificationReceipt.next_retry_at <= now,
            )
            .order_by(NotificationReceipt.next_retry_at)
            .limit(limit)
            .all()
        )

    def get_receipts(
        self, user_id: int | None = None, channel: str | None = None,
        limit: int = 20, offset: int = 0,
    ) -> list[NotificationReceipt]:
        query = self._db.query(NotificationReceipt)
        if user_id is not None:
            query = query.filter(NotificationReceipt.user_id == user_id)
        if channel is not None:
            query = query.filter(NotificationReceipt.channel == channel)
        return query.order_by(NotificationReceipt.created_at.desc()).limit(limit).offset(offset).all()

    def get_stats(self, user_id: int | None = None) -> dict[str, Any]:
        query = self._db.query(NotificationReceipt)
        if user_id is not None:
            query = query.filter(NotificationReceipt.user_id == user_id)
        total = query.count()
        sent = query.filter(NotificationReceipt.status == "sent").count()
        failed = query.filter(NotificationReceipt.status == "failed").count()
        pending = query.filter(NotificationReceipt.status == "pending").count()
        return {
            "total": total,
            "sent": sent,
            "failed": failed,
            "pending": pending,
            "delivery_rate": round(sent / total * 100, 1) if total else 0.0,
        }
