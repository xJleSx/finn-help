from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from src.db.models import ChannelPreference, MutedAlert, UserProfileModel, UserSetting

logger = structlog.get_logger(__name__)

RISK_MULTIPLIERS = {
    "conservative": 0.7,
    "balanced": 1.0,
    "aggressive": 1.3,
}

DEFAULT_PREFS: dict[str, Any] = {
    "min_severity": "LOW",
    "max_daily": 50,
    "quiet_hours": {"start": None, "end": None},
    "muted_tickers": [],
    "preferred_channels": ["telegram", "email", "web"],
    "risk_based_thresholds": True,
}

COOLDOWN_SECONDS: dict[str, int] = {
    "signal": 300,
    "daily": 3600,
    "geo": 600,
    "dividend": 86400,
    "trade": 60,
}

DEDUP_WINDOW_SECONDS: dict[str, int] = {
    "signal": 60,
    "daily": 300,
    "geo": 120,
    "dividend": 3600,
    "trade": 30,
}


class FrequencyController:
    def __init__(self) -> None:
        self._daily_counts: dict[int, list[float]] = {}
        self._last_sent: dict[tuple[int, str], float] = {}
        self._dedup_cache: dict[tuple[int, str, str], float] = {}

    def allow_notification(
        self,
        user_id: int,
        notif_type: str,
        ticker: str | None = None,
        max_daily: int = 50,
        quiet_hours: dict[str, str | None] | None = None,
    ) -> bool:
        now = time.time()

        if self._exceeded_daily_limit(user_id, now, max_daily):
            return False

        cooldown = COOLDOWN_SECONDS.get(notif_type, 60)
        last = self._last_sent.get((user_id, notif_type))
        if last is not None and (now - last) < cooldown:
            return False

        if quiet_hours and self._in_quiet_hours(quiet_hours):
            return False

        if ticker:
            dedup_window = DEDUP_WINDOW_SECONDS.get(notif_type, 30)
            dedup_key = (user_id, notif_type, ticker)
            last_dedup = self._dedup_cache.get(dedup_key)
            if last_dedup is not None and (now - last_dedup) < dedup_window:
                return False

        return True

    def record_notification(self, user_id: int, notif_type: str, ticker: str | None = None) -> None:
        now = time.time()

        if user_id not in self._daily_counts:
            self._daily_counts[user_id] = []
        self._daily_counts[user_id].append(now)
        self._trim_daily_counts(user_id, now)

        self._last_sent[(user_id, notif_type)] = now

        if ticker:
            self._dedup_cache[(user_id, notif_type, ticker)] = now

    def _exceeded_daily_limit(self, user_id: int, now: float, max_daily: int) -> bool:
        self._trim_daily_counts(user_id, now)
        return len(self._daily_counts.get(user_id, [])) >= max_daily

    def _trim_daily_counts(self, user_id: int, now: float) -> None:
        cutoff = now - 86400
        records = self._daily_counts.get(user_id, [])
        self._daily_counts[user_id] = [t for t in records if t > cutoff]

    @staticmethod
    def _in_quiet_hours(qh: dict[str, str | None]) -> bool:
        start = qh.get("start")
        end = qh.get("end")
        if not start or not end:
            return False
        now = datetime.now(timezone.utc)
        now_time = now.strftime("%H:%M")
        if start <= end:
            return start <= now_time <= end
        return now_time >= start or now_time <= end


class NotificationPreferencesEngine:
    def __init__(self, db: Session, frequency_controller: FrequencyController | None = None) -> None:
        self._db = db
        self._frequency = frequency_controller or FrequencyController()

    @property
    def frequency(self) -> FrequencyController:
        return self._frequency

    def get_user_preferences(self, user_id: int) -> dict[str, Any]:
        prefs = dict(DEFAULT_PREFS)

        rows = self._db.query(UserSetting).limit(1000).all()
        if self._db.query(UserSetting).count() > 1000:
            logger.warning("More than 1000 UserSetting rows exist — consider adding user_id filter")
        for row in rows:
            if row.key.startswith(f"notify_prefs_{user_id}_"):
                key = row.key.replace(f"notify_prefs_{user_id}_", "")
                self._apply_setting(prefs, key, row.value)

        profile = self._db.query(UserProfileModel).filter_by(user_id=user_id).first()
        if profile:
            prefs["risk_profile"] = profile.risk_profile
            prefs["capital"] = profile.capital

        muted = self._db.query(MutedAlert).filter_by(user_id=user_id).all()
        prefs["muted_tickers"] = [m.ticker for m in muted]

        channels = self._db.query(ChannelPreference).filter_by(user_id=user_id).all()
        enabled = []
        for ch in channels:
            if ch.enabled is not False:
                enabled.append(ch.channel)
        if enabled:
            prefs["preferred_channels"] = enabled

        return prefs

    def update_preferences(self, user_id: int, prefs: dict[str, Any]) -> None:
        for key, value in prefs.items():
            setting_key = f"notify_prefs_{user_id}_{key}"
            existing = self._db.query(UserSetting).filter_by(key=setting_key).first()
            if existing:
                existing.value = str(value)
            else:
                self._db.add(UserSetting(key=setting_key, value=str(value)))
        self._db.commit()

    def get_preferred_channels(self, user_id: int) -> list[str]:
        channels = self._db.query(ChannelPreference).filter_by(user_id=user_id).all()
        if not channels:
            return list(DEFAULT_PREFS["preferred_channels"])
        return [ch.channel for ch in channels if ch.enabled is not False]

    def get_effective_threshold(self, user_id: int, base_threshold: float) -> float:
        profile = self._db.query(UserProfileModel).filter_by(user_id=user_id).first()
        risk_profile = profile.risk_profile if profile else "balanced"
        multiplier = RISK_MULTIPLIERS.get(risk_profile, 1.0)
        return base_threshold * multiplier

    @staticmethod
    def _apply_setting(prefs: dict[str, Any], key: str, value: str) -> None:
        if key == "max_daily":
            prefs["max_daily"] = int(value)
        elif key == "min_severity":
            prefs["min_severity"] = value
        elif key == "quiet_hours_start":
            prefs.setdefault("quiet_hours", {})["start"] = value if value != "None" else None
        elif key == "quiet_hours_end":
            prefs.setdefault("quiet_hours", {})["end"] = value if value != "None" else None
        elif key == "risk_based_thresholds":
            prefs["risk_based_thresholds"] = value.lower() == "true"
