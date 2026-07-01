from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.db.models import MutedAlert, UserSetting

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

                muted_rows = (
                    db_session.query(MutedAlert.ticker)
                    .filter_by(user_id=user_id)
                    .all()
                )
                for row in muted_rows:
                    if row.ticker not in prefs["muted_tickers"]:
                        prefs["muted_tickers"].append(row.ticker)
            except Exception:
                logger.warning("Failed to load alert prefs for user %d", user_id)

        self._db_preferences[user_id] = prefs
        return prefs

    def set_preferences(
        self, user_id: int, db_session: Any | None = None, **kwargs: Any,
    ) -> None:
        if db_session is None:
            logger.warning("set_preferences: no db_session provided")
            return
        for key, value in kwargs.items():
            if key not in ("min_severity", "quiet_hours_start", "quiet_hours_end"):
                continue
            setting_key = f"alert_prefs_{user_id}_{key}"
            row = db_session.query(UserSetting).filter_by(key=setting_key).first()
            if value is not None:
                if row:
                    row.value = str(value)
                else:
                    db_session.add(UserSetting(key=setting_key, value=str(value)))
            else:
                if row:
                    db_session.delete(row)
        db_session.commit()
        self.clear_cache(user_id)

    def mute_ticker(self, user_id: int, ticker: str, db_session: Any | None = None) -> bool:
        if db_session is None:
            return False
        ticker = ticker.upper()
        existing = (
            db_session.query(MutedAlert)
            .filter_by(user_id=user_id, ticker=ticker, alert_type=None)
            .first()
        )
        if existing:
            return False
        db_session.add(MutedAlert(user_id=user_id, ticker=ticker, alert_type=None))
        db_session.commit()
        self.clear_cache(user_id)
        return True

    def unmute_ticker(self, user_id: int, ticker: str, db_session: Any | None = None) -> bool:
        if db_session is None:
            return False
        ticker = ticker.upper()
        rows = (
            db_session.query(MutedAlert)
            .filter_by(user_id=user_id, ticker=ticker)
            .all()
        )
        if not rows:
            return False
        for row in rows:
            db_session.delete(row)
        db_session.commit()
        self.clear_cache(user_id)
        return True

    def get_muted_tickers(self, user_id: int, db_session: Any | None = None) -> list[str]:
        if db_session is None:
            return []
        rows = (
            db_session.query(MutedAlert.ticker)
            .filter_by(user_id=user_id)
            .all()
        )
        return list({r.ticker for r in rows})

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
