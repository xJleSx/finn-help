from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


class AlertAggregator:
    def __init__(self, window_minutes: int = 60) -> None:
        self._window = timedelta(minutes=window_minutes)

    def aggregate(self, alerts: list[dict[str, Any]]) -> dict[str, Any]:
        if not alerts:
            return {"summary": "No alerts", "count": 0, "alerts": []}

        now = datetime.now(timezone.utc)
        window_start = now - self._window
        recent = [a for a in alerts if self._parse_ts(a) >= window_start]

        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for alert in recent:
            cat = alert.get("category", alert.get("alert_type", "GENERAL"))
            ticker = alert.get("ticker", "N/A")
            groups[(cat, ticker)].append(alert)

        summary_parts: list[str] = []
        all_grouped: list[dict[str, Any]] = []
        total_count = 0
        for (cat, ticker), group in groups.items():
            count = len(group)
            total_count += count
            summary_parts.append(f"{count} {cat} alerts about {ticker}")
            all_grouped.extend(group)

        remaining = [a for a in alerts if a not in all_grouped]
        all_grouped.extend(remaining)

        return {
            "summary": "; ".join(summary_parts) if summary_parts else "No recent alerts",
            "count": total_count,
            "alerts": all_grouped,
        }

    @staticmethod
    def _parse_ts(alert: dict[str, Any]) -> datetime:
        raw = alert.get("timestamp", alert.get("created_at", alert.get("published_at", "")))
        if isinstance(raw, datetime):
            return raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
        if isinstance(raw, str):
            try:
                dt = datetime.fromisoformat(raw)
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                logger.debug("Failed to parse date string: %s", raw)
        return datetime.now(timezone.utc)
