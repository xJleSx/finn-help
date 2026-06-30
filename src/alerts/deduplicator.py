from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.db.models import News


class AlertDeduplicator:
    def __init__(self, hours: int = 24) -> None:
        self._hours = hours
        self._seen: dict[str, datetime] = {}

    def is_duplicate(self, article: News) -> bool:
        key = f"{article.category}:{article.subcategory}:{article.source_name}"
        now = datetime.now(timezone.utc)
        last = self._seen.get(key)
        if last and (now - last).total_seconds() < self._hours * 3600:
            return True
        self._seen[key] = now
        return False

    def reset(self) -> None:
        self._seen.clear()


class AlertTimer:
    def __init__(self, cooldown_minutes: int = 60) -> None:
        self._cooldown = cooldown_minutes
        self._last_sent: dict[str, datetime] = {}

    def can_send(self, ticker: str) -> bool:
        now = datetime.now(timezone.utc)
        last = self._last_sent.get(ticker)
        if last and (now - last).total_seconds() < self._cooldown * 60:
            return False
        self._last_sent[ticker] = now
        return True

    def reset(self) -> None:
        self._last_sent.clear()
