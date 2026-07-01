from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import structlog

from src.config import settings
from src.db.models import ChannelPreference
from src.notifications.templates.renderer import AlertTemplateRenderer

logger = structlog.get_logger(__name__)

CHANNEL_TELEGRAM = "telegram"
CHANNEL_EMAIL = "email"
CHANNEL_WEB = "web"
ALL_CHANNELS = frozenset({CHANNEL_TELEGRAM, CHANNEL_EMAIL, CHANNEL_WEB})

SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


@dataclass
class PushMessage:
    title: str
    body: str
    ticker: str = ""
    priority: str = "LOW"
    alert_type: str = "general"
    user_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


_renderer = AlertTemplateRenderer()


def _severity_level(priority: str | float) -> int:
    if isinstance(priority, (int, float)):
        return 2 if priority >= 0.6 else 1 if priority >= 0.4 else 0
    return SEVERITY_ORDER.get(priority, 0)


def load_preferences(db: Any, user_id: int) -> dict[str, dict[str, Any]]:
    rows = db.query(ChannelPreference).filter_by(user_id=user_id).all()
    prefs: dict[str, dict[str, Any]] = {}
    for row in rows:
        prefs[row.channel] = {
            "enabled": row.enabled if row.enabled is not None else True,
            "min_severity": row.min_severity or "LOW",
            "quiet_hours_start": row.quiet_hours_start,
            "quiet_hours_end": row.quiet_hours_end,
        }
    for ch in ALL_CHANNELS:
        if ch not in prefs:
            prefs[ch] = {
                "enabled": True,
                "min_severity": "LOW",
                "quiet_hours_start": None,
                "quiet_hours_end": None,
            }
    return prefs


def set_preference(db: Any, user_id: int, channel: str, **kwargs: Any) -> None:
    row = db.query(ChannelPreference).filter_by(user_id=user_id, channel=channel).first()
    if row is None:
        row = ChannelPreference(user_id=user_id, channel=channel)
        db.add(row)
    for key, value in kwargs.items():
        if hasattr(row, key):
            setattr(row, key, value)
    db.commit()


def _in_quiet_hours(prefs: dict[str, Any]) -> bool:
    qh_start = prefs.get("quiet_hours_start")
    qh_end = prefs.get("quiet_hours_end")
    if not qh_start or not qh_end:
        return False
    now = datetime.now(timezone.utc)
    now_time = now.strftime("%H:%M")
    if qh_start <= qh_end:
        return qh_start <= now_time <= qh_end
    return now_time >= qh_start or now_time <= qh_end


def should_send(channel_prefs: dict[str, Any], msg: PushMessage) -> bool:
    if not channel_prefs.get("enabled", True):
        return False
    min_level = SEVERITY_ORDER.get(channel_prefs.get("min_severity", "LOW"), 0)
    msg_level = _severity_level(msg.priority)
    if msg_level < min_level:
        return False
    if _in_quiet_hours(channel_prefs) and msg_level < 3:
        return False
    return True


class EmailPushChannel:
    def __init__(self) -> None:
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._user = settings.smtp_user
        self._password = settings.smtp_password
        self._from_email = settings.smtp_from_email

    @property
    def available(self) -> bool:
        return bool(self._host and self._user and self._password)

    @staticmethod
    def _resolve_email_template(msg: PushMessage) -> str:
        alert_type_templates = {
            "signal": "signal.html.j2",
            "daily": "daily.html.j2",
            "dividend": "alert.html.j2",
            "rebalance": "alert.html.j2",
            "divergence": "alert.html.j2",
            "price_target": "alert.html.j2",
            "general": "alert.html.j2",
        }
        return alert_type_templates.get(msg.alert_type, "alert.html.j2")

    def send(self, to_email: str, msg: PushMessage) -> bool:
        if not self.available:
            logger.warning("email_channel_not_configured")
            return False
        try:
            email_template_name = self._resolve_email_template(msg)
            html = _renderer.render_email(email_template_name, **msg.data, title=msg.title, body=msg.body, ticker=msg.ticker, alert_type=msg.alert_type, priority=msg.priority)
            mime = MIMEMultipart("alternative")
            mime["Subject"] = f"[Finn] {msg.title}"
            mime["From"] = self._from_email
            mime["To"] = to_email
            mime.attach(MIMEText(msg.body, "plain", "utf-8"))
            mime.attach(MIMEText(html, "html", "utf-8"))

            with smtplib.SMTP(self._host, self._port, timeout=15) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                if self._user:
                    server.login(self._user, self._password)
                server.sendmail(self._from_email, [to_email], mime.as_string())

            logger.info("email_sent", to=to_email, subject=msg.title)
            return True
        except Exception as e:
            logger.error("email_failed", to=to_email, error=str(e))
            return False


class WebPushChannel:
    def __init__(self) -> None:
        self._connections: dict[int, list[Any]] = {}

    @property
    def available(self) -> bool:
        return True

    def register(self, user_id: int, connection: Any) -> None:
        self._connections.setdefault(user_id, []).append(connection)

    def unregister(self, user_id: int, connection: Any) -> None:
        conns = self._connections.get(user_id, [])
        if connection in conns:
            conns.remove(connection)

    def send(self, user_id: int, msg: PushMessage) -> bool:
        conns = self._connections.get(user_id, [])
        if not conns:
            return False
        payload = {
            "type": "alert",
            "title": msg.title,
            "body": msg.body,
            "ticker": msg.ticker,
            "priority": msg.priority,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for conn in conns:
            try:
                conn(payload)
            except Exception:
                logger.exception("web_push_failed", user_id=user_id)
        return True


class PushManager:
    def __init__(self, db: Any | None = None) -> None:
        self._db = db
        self.email = EmailPushChannel()
        self.web = WebPushChannel()
        self._telegram_handler: Any = None

    def set_telegram_handler(self, handler: Any) -> None:
        self._telegram_handler = handler

    def send(self, user_id: int, to_email: str | None, msg: PushMessage, db: Any | None = None) -> dict[str, bool]:
        session = db or self._db
        results: dict[str, bool] = {}

        if session is None:
            logger.warning("push_manager_no_db", user_id=user_id)
            return results

        prefs = load_preferences(session, user_id)

        if should_send(prefs.get("email", {}), msg) and to_email:
            results["email"] = self.email.send(to_email, msg)

        if should_send(prefs.get("web", {}), msg):
            results["web"] = self.web.send(user_id, msg)

        if should_send(prefs.get("telegram", {}), msg) and self._telegram_handler:
            try:
                self._telegram_handler(user_id, msg)
                results["telegram"] = True
            except Exception:
                logger.exception("telegram_push_failed", user_id=user_id)
                results["telegram"] = False

        return results
