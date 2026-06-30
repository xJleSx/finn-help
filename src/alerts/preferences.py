from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class UserAlertPreferences:
    SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

    def __init__(self, user_id: int | None = None) -> None:
        self.user_id = user_id
        self._db_preferences: dict[int, dict[str, Any]] = {}

    def get_preferences(self, user_id: int, db_session: Any | None = None) -> dict[str, Any]:
        cached = self._db_preferences.get(user_id)
        if cached is not None:
            return cached

        prefs: dict[str, Any] = {
            "min_severity": "LOW",
            "muted_tickers": [],
            "quiet_hours_start": None,
            "quiet_hours_end": None,
        }

        if db_session is not None:
            try:
                from src.db.models import UserSetting

                rows = db_session.query(UserSetting).filter(
                    UserSetting.key.like(f"alert_prefs_{user_id}_%")
                ).all()
                for row in rows:
                    key = row.key.replace(f"alert_prefs_{user_id}_", "")
                    if key == "min_severity":
                        prefs["min_severity"] = row.value
                    elif key == "muted_tickers":
                        prefs["muted_tickers"] = json.loads(row.value)
                    elif key == "quiet_hours_start":
                        prefs["quiet_hours_start"] = row.value
                    elif key == "quiet_hours_end":
                        prefs["quiet_hours_end"] = row.value
            except Exception:
                logger.warning("Failed to load alert prefs for user %d", user_id)

        self._db_preferences[user_id] = prefs
        return prefs

    def filter_alerts(
        self, alerts: list[dict[str, Any]], preferences: dict[str, Any],
    ) -> list[dict[str, Any]]:
        min_severity = preferences.get("min_severity", "LOW")
        muted = set(preferences.get("muted_tickers", []))
        qh_start = preferences.get("quiet_hours_start")
        qh_end = preferences.get("quiet_hours_end")

        min_level = self.SEVERITY_ORDER.get(min_severity, 0)

        now = datetime.now(timezone.utc)
        now_time = now.strftime("%H:%M")

        in_quiet_hours = False
        if qh_start and qh_end:
            if qh_start <= qh_end:
                in_quiet_hours = qh_start <= now_time <= qh_end
            else:
                in_quiet_hours = now_time >= qh_start or now_time <= qh_end

        result = []
        for alert in alerts:
            priority = alert.get("priority", alert.get("severity", "LOW"))
            if isinstance(priority, (int, float)):
                alert_level = 2 if priority >= 0.6 else 1 if priority >= 0.4 else 0
            else:
                alert_level = self.SEVERITY_ORDER.get(priority, 0)
            if alert_level < min_level:
                continue

            ticker = alert.get("ticker", "")
            if ticker in muted:
                continue

            if in_quiet_hours:
                if alert_level < 3:
                    continue

            result.append(alert)

        return result

    def clear_cache(self, user_id: int | None = None) -> None:
        if user_id:
            self._db_preferences.pop(user_id, None)
        else:
            self._db_preferences.clear()
