from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.db.models import ChannelPreference, Base
from src.notifications.channels import (
    ALL_CHANNELS,
    EmailPushChannel,
    PushManager,
    PushMessage,
    WebPushChannel,
    load_preferences,
    set_preference,
    should_send,
    _severity_level,
    _in_quiet_hours,
)
from src.config import settings


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class TestSeverityLevel:
    def test_string_priority(self):
        assert _severity_level("LOW") == 0
        assert _severity_level("MEDIUM") == 1
        assert _severity_level("HIGH") == 2
        assert _severity_level("CRITICAL") == 3

    def test_numeric_priority(self):
        assert _severity_level(0.3) == 0
        assert _severity_level(0.5) == 1
        assert _severity_level(0.7) == 2

    def test_unknown_defaults_to_zero(self):
        assert _severity_level("UNKNOWN") == 0


class TestShouldSend:
    def test_disabled_channel(self):
        assert not should_send({"enabled": False, "min_severity": "LOW"}, PushMessage(title="", body=""))

    def test_below_min_severity(self):
        assert not should_send(
            {"enabled": True, "min_severity": "HIGH"},
            PushMessage(title="", body="", priority="LOW"),
        )

    def test_above_min_severity(self):
        assert should_send(
            {"enabled": True, "min_severity": "LOW"},
            PushMessage(title="", body="", priority="HIGH"),
        )

    def test_quiet_hours_blocks_non_critical(self):
        now = datetime.now(timezone.utc)
        with patch("src.notifications.channels.datetime") as mock_dt:
            mock_dt.now.return_value = now.replace(hour=23, minute=0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = should_send(
                {
                    "enabled": True,
                    "min_severity": "LOW",
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "08:00",
                },
                PushMessage(title="", body="", priority="HIGH"),
            )
            assert not result

    def test_quiet_hours_allows_critical(self):
        now = datetime.now(timezone.utc)
        with patch("src.notifications.channels.datetime") as mock_dt:
            mock_dt.now.return_value = now.replace(hour=23, minute=0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = should_send(
                {
                    "enabled": True,
                    "min_severity": "LOW",
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "08:00",
                },
                PushMessage(title="", body="", priority="CRITICAL"),
            )
            assert result


class TestLoadPreferences:
    def test_empty_db_returns_defaults(self, db_session):
        prefs = load_preferences(db_session, user_id=1)
        for ch in ALL_CHANNELS:
            assert ch in prefs
            assert prefs[ch]["enabled"] is True
            assert prefs[ch]["min_severity"] == "LOW"

    def test_loads_existing_prefs(self, db_session):
        pref = ChannelPreference(user_id=1, channel="email", enabled=False, min_severity="HIGH")
        db_session.add(pref)
        db_session.commit()
        prefs = load_preferences(db_session, user_id=1)
        assert prefs["email"]["enabled"] is False
        assert prefs["email"]["min_severity"] == "HIGH"

    def test_isolated_by_user(self, db_session):
        pref = ChannelPreference(user_id=1, channel="email", enabled=False)
        db_session.add(pref)
        db_session.commit()
        prefs = load_preferences(db_session, user_id=2)
        assert prefs["email"]["enabled"] is True


class TestSetPreference:
    def test_creates_new_row(self, db_session):
        set_preference(db_session, user_id=1, channel="email", enabled=False, min_severity="HIGH")
        row = db_session.query(ChannelPreference).filter_by(user_id=1, channel="email").first()
        assert row is not None
        assert row.enabled is False
        assert row.min_severity == "HIGH"

    def test_updates_existing_row(self, db_session):
        pref = ChannelPreference(user_id=1, channel="email", enabled=True)
        db_session.add(pref)
        db_session.commit()
        set_preference(db_session, user_id=1, channel="email", enabled=False)
        db_session.refresh(pref)
        assert pref.enabled is False

    def test_ignores_unknown_kwargs(self, db_session):
        set_preference(db_session, user_id=1, channel="email", unknown_field="test")
        row = db_session.query(ChannelPreference).filter_by(user_id=1, channel="email").first()
        assert row is not None


class TestInQuietHours:
    def test_no_quiet_hours(self):
        assert _in_quiet_hours({}) is False

    def test_within_quiet_hours(self):
        now = datetime.now(timezone.utc)
        with patch("src.notifications.channels.datetime") as mock_dt:
            mock_dt.now.return_value = now.replace(hour=23, minute=0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _in_quiet_hours({"quiet_hours_start": "22:00", "quiet_hours_end": "08:00"})

    def test_outside_quiet_hours(self):
        now = datetime.now(timezone.utc)
        with patch("src.notifications.channels.datetime") as mock_dt:
            mock_dt.now.return_value = now.replace(hour=10, minute=0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert not _in_quiet_hours({"quiet_hours_start": "22:00", "quiet_hours_end": "08:00"})


class TestEmailPushChannel:
    def test_not_available_when_not_configured(self):
        with patch.object(settings, "smtp_host", ""):
            channel = EmailPushChannel()
            assert not channel.available

    def test_available_when_configured(self):
        with (
            patch.object(settings, "smtp_host", "smtp.example.com"),
            patch.object(settings, "smtp_user", "user"),
            patch.object(settings, "smtp_password", "pass"),
        ):
            channel = EmailPushChannel()
            assert channel.available

    def test_send_returns_false_when_not_available(self):
        with patch.object(settings, "smtp_host", ""):
            channel = EmailPushChannel()
            result = channel.send("test@example.com", PushMessage(title="Test", body="Hello"))
            assert result is False

    def test_send_success(self):
        with (
            patch.object(settings, "smtp_host", "smtp.example.com"),
            patch.object(settings, "smtp_user", "user"),
            patch.object(settings, "smtp_password", "pass"),
            patch.object(settings, "smtp_from_email", "from@example.com"),
            patch("src.notifications.channels.smtplib.SMTP") as mock_smtp,
        ):
            channel = EmailPushChannel()
            result = channel.send("to@example.com", PushMessage(title="Alert", body="Something happened"))
            assert result is True
            mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=15)
            mock_smtp.return_value.__enter__.return_value.sendmail.assert_called_once()

    def test_send_returns_false_on_exception(self):
        with (
            patch.object(settings, "smtp_host", "smtp.example.com"),
            patch.object(settings, "smtp_user", "user"),
            patch.object(settings, "smtp_password", "pass"),
            patch.object(settings, "smtp_from_email", "from@example.com"),
            patch("src.notifications.channels.smtplib.SMTP", side_effect=Exception("SMTP error")),
        ):
            channel = EmailPushChannel()
            result = channel.send("to@example.com", PushMessage(title="Test", body="Hello"))
            assert result is False


class TestWebPushChannel:
    def test_available_by_default(self):
        channel = WebPushChannel()
        assert channel.available

    def test_register_and_send(self):
        channel = WebPushChannel()
        handler = MagicMock()
        channel.register(1, handler)
        msg = PushMessage(title="Test", body="Body", ticker="SBER", priority="HIGH")
        result = channel.send(1, msg)
        assert result is True
        handler.assert_called_once()
        payload = handler.call_args[0][0]
        assert payload["title"] == "Test"
        assert payload["ticker"] == "SBER"

    def test_unregister(self):
        channel = WebPushChannel()
        handler = MagicMock()
        channel.register(1, handler)
        channel.unregister(1, handler)
        result = channel.send(1, PushMessage(title="", body=""))
        assert result is False

    def test_send_no_connections(self):
        channel = WebPushChannel()
        result = channel.send(999, PushMessage(title="", body=""))
        assert result is False


class TestPushManager:
    def test_send_all_channels_disabled(self, db_session):
        set_preference(db_session, user_id=1, channel="email", enabled=False)
        set_preference(db_session, user_id=1, channel="web", enabled=False)
        set_preference(db_session, user_id=1, channel="telegram", enabled=False)
        manager = PushManager(db=db_session)
        msg = PushMessage(title="Test", body="Body")
        results = manager.send(1, "test@example.com", msg, db=db_session)
        assert results == {}

    def test_send_email_only(self, db_session):
        set_preference(db_session, user_id=1, channel="email", enabled=True, min_severity="LOW")
        manager = PushManager(db=db_session)
        msg = PushMessage(title="Test", body="Body")
        with patch.object(manager.email, "send", return_value=True):
            results = manager.send(1, "test@example.com", msg, db=db_session)
            assert results.get("email") is True

    def test_send_telegram(self, db_session):
        set_preference(db_session, user_id=1, channel="telegram", enabled=True, min_severity="LOW")
        manager = PushManager(db=db_session)
        handler = MagicMock()
        manager.set_telegram_handler(handler)
        msg = PushMessage(title="Test", body="Body")
        results = manager.send(1, None, msg, db=db_session)
        assert results.get("telegram") is True
        handler.assert_called_once_with(1, msg)

    def test_send_telegram_error(self, db_session):
        set_preference(db_session, user_id=1, channel="telegram", enabled=True, min_severity="LOW")
        manager = PushManager(db=db_session)
        handler = MagicMock(side_effect=Exception("fail"))
        manager.set_telegram_handler(handler)
        msg = PushMessage(title="Test", body="Body")
        results = manager.send(1, None, msg, db=db_session)
        assert results.get("telegram") is False

    def test_send_web(self, db_session):
        set_preference(db_session, user_id=1, channel="web", enabled=True, min_severity="LOW")
        manager = PushManager(db=db_session)
        handler = MagicMock()
        manager.web.register(1, handler)
        msg = PushMessage(title="Test", body="Body")
        results = manager.send(1, None, msg, db=db_session)
        assert results.get("web") is True

    def test_send_no_db(self):
        manager = PushManager()
        msg = PushMessage(title="Test", body="Body")
        results = manager.send(1, None, msg)
        assert results == {}
