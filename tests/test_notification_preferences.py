from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.db.models import Base, ChannelPreference, MutedAlert, UserProfileModel, UserSetting
from src.notifications.preferences import FrequencyController, NotificationPreferencesEngine
from src.notifications.preferences.engine import COOLDOWN_SECONDS, DEDUP_WINDOW_SECONDS, RISK_MULTIPLIERS


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def freq() -> FrequencyController:
    return FrequencyController()


@pytest.fixture
def engine(db_session) -> NotificationPreferencesEngine:
    return NotificationPreferencesEngine(db_session)


# ── FrequencyController ─────────────────────────────────────────────────────


class TestFrequencyControllerAllow:
    def test_allows_first_notification(self, freq):
        assert freq.allow_notification(1, "signal") is True

    def test_blocks_after_max_daily(self, freq):
        for i in range(50):
            with patch("time.time", return_value=time.time() + i * 1000):
                freq.record_notification(1, "signal")
        with patch("time.time", return_value=time.time() + 50000):
            assert freq.allow_notification(1, "signal", max_daily=50) is False

    def test_allows_under_max_daily(self, freq):
        for i in range(49):
            with patch("time.time", return_value=time.time() + i * 1000):
                freq.record_notification(1, "signal")
        with patch("time.time", return_value=time.time() + 50000):
            assert freq.allow_notification(1, "signal", max_daily=50) is True

    def test_blocks_during_cooldown(self, freq):
        freq.record_notification(1, "signal")
        assert freq.allow_notification(1, "signal") is False

    def test_allows_after_cooldown_expires(self, freq):
        freq.record_notification(1, "signal")
        cooldown = COOLDOWN_SECONDS["signal"]
        with patch("time.time", return_value=time.time() + cooldown + 1):
            assert freq.allow_notification(1, "signal") is True

    def test_cooldown_per_type_independent(self, freq):
        freq.record_notification(1, "signal")
        assert freq.allow_notification(1, "daily") is True

    def test_dedup_blocks_same_ticker(self, freq):
        base = time.time() + 50000
        with patch("time.time", return_value=base):
            freq.record_notification(1, "signal", ticker="SBER")
        with patch("time.time", return_value=base + 10):
            assert freq.allow_notification(1, "signal", ticker="SBER") is False

    def test_dedup_allows_different_ticker(self, freq):
        base = time.time() + 50000
        with patch("time.time", return_value=base):
            freq.record_notification(1, "signal", ticker="SBER")
        with patch("time.time", return_value=base + 10):
            assert freq.allow_notification(1, "signal", ticker="GAZP") is False
        cooldown = COOLDOWN_SECONDS["signal"]
        with patch("time.time", return_value=base + cooldown + 10):
            assert freq.allow_notification(1, "signal", ticker="GAZP") is True

    def test_dedup_window_expires(self, freq):
        initial = time.time() + 10000
        cooldown = COOLDOWN_SECONDS["signal"]
        dedup_win = DEDUP_WINDOW_SECONDS["signal"]
        with patch("time.time", return_value=initial):
            freq.record_notification(1, "signal", ticker="SBER")
        expiry = initial + max(cooldown, dedup_win) + 10
        with patch("time.time", return_value=expiry):
            assert freq.allow_notification(1, "signal", ticker="SBER") is True

    def test_custom_max_daily(self, freq):
        for i in range(5):
            with patch("time.time", return_value=time.time() + i * 1000):
                freq.record_notification(1, "signal")
        with patch("time.time", return_value=time.time() + 10000):
            assert freq.allow_notification(1, "signal", max_daily=5) is False
        with patch("time.time", return_value=time.time() + 20000):
            assert freq.allow_notification(1, "signal", max_daily=10) is True

    def test_quiet_hours_blocks(self, freq):
        qh = {"start": "22:00", "end": "08:00"}
        with patch("src.notifications.preferences.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc)
            assert freq.allow_notification(1, "signal", quiet_hours=qh) is False

    def test_quiet_hours_allows_outside(self, freq):
        qh = {"start": "22:00", "end": "08:00"}
        with patch("src.notifications.preferences.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
            assert freq.allow_notification(1, "signal", quiet_hours=qh) is True

    def test_no_quiet_hours(self, freq):
        assert freq.allow_notification(1, "signal", quiet_hours=None) is True
        assert freq.allow_notification(1, "signal", quiet_hours={}) is True
        assert freq.allow_notification(1, "signal", quiet_hours={"start": None, "end": None}) is True

    def test_daily_counts_expire_after_24h(self, freq):
        for _ in range(50):
            freq.record_notification(1, "signal")
        with patch("time.time", return_value=time.time() + 86401):
            assert freq.allow_notification(1, "signal", max_daily=50) is True

    def test_per_user_isolation(self, freq):
        freq.record_notification(1, "signal")
        assert freq.allow_notification(2, "signal") is True


# ── NotificationPreferencesEngine ───────────────────────────────────────────


class TestGetUserPreferences:
    def test_default_prefs_when_no_db_data(self, engine, db_session):
        prefs = engine.get_user_preferences(1)
        assert prefs["min_severity"] == "LOW"
        assert prefs["max_daily"] == 50
        assert prefs["preferred_channels"] == ["telegram", "email", "web"]

    def test_loads_user_settings(self, engine, db_session):
        db_session.add(UserSetting(key="notify_prefs_1_min_severity", value="HIGH"))
        db_session.add(UserSetting(key="notify_prefs_1_max_daily", value="10"))
        db_session.commit()
        prefs = engine.get_user_preferences(1)
        assert prefs["min_severity"] == "HIGH"
        assert prefs["max_daily"] == 10

    def test_loads_quiet_hours(self, engine, db_session):
        db_session.add(UserSetting(key="notify_prefs_1_quiet_hours_start", value="22:00"))
        db_session.add(UserSetting(key="notify_prefs_1_quiet_hours_end", value="08:00"))
        db_session.commit()
        prefs = engine.get_user_preferences(1)
        assert prefs["quiet_hours"]["start"] == "22:00"
        assert prefs["quiet_hours"]["end"] == "08:00"

    def test_loads_user_profile(self, engine, db_session):
        profile = UserProfileModel(user_id=1, risk_profile="aggressive", capital=500000.0)
        db_session.add(profile)
        db_session.commit()
        prefs = engine.get_user_preferences(1)
        assert prefs["risk_profile"] == "aggressive"
        assert prefs["capital"] == 500000.0

    def test_loads_muted_tickers(self, engine, db_session):
        db_session.add(MutedAlert(user_id=1, ticker="SBER"))
        db_session.add(MutedAlert(user_id=1, ticker="GAZP"))
        db_session.commit()
        prefs = engine.get_user_preferences(1)
        assert "SBER" in prefs["muted_tickers"]
        assert "GAZP" in prefs["muted_tickers"]

    def test_loads_preferred_channels(self, engine, db_session):
        db_session.add(ChannelPreference(user_id=1, channel="telegram", enabled=True))
        db_session.add(ChannelPreference(user_id=1, channel="email", enabled=False))
        db_session.commit()
        prefs = engine.get_user_preferences(1)
        assert "telegram" in prefs["preferred_channels"]
        assert "email" not in prefs["preferred_channels"]

    def test_isolated_by_user(self, engine, db_session):
        db_session.add(UserSetting(key="notify_prefs_1_min_severity", value="HIGH"))
        db_session.commit()
        prefs = engine.get_user_preferences(2)
        assert prefs["min_severity"] == "LOW"

    def test_no_profile_returns_defaults(self, engine, db_session):
        prefs = engine.get_user_preferences(999)
        assert "risk_profile" not in prefs
        assert "capital" not in prefs


class TestUpdatePreferences:
    def test_creates_new_settings(self, engine, db_session):
        engine.update_preferences(1, {"max_daily": "25", "min_severity": "HIGH"})
        rows = db_session.query(UserSetting).all()
        keys = [r.key for r in rows]
        assert "notify_prefs_1_max_daily" in keys
        assert "notify_prefs_1_min_severity" in keys

    def test_updates_existing_settings(self, engine, db_session):
        db_session.add(UserSetting(key="notify_prefs_1_max_daily", value="50"))
        db_session.commit()
        engine.update_preferences(1, {"max_daily": "30"})
        row = db_session.query(UserSetting).filter_by(key="notify_prefs_1_max_daily").first()
        assert row.value == "30"

    def test_isolated_per_user(self, engine, db_session):
        engine.update_preferences(1, {"max_daily": "10"})
        engine.update_preferences(2, {"max_daily": "20"})
        row1 = db_session.query(UserSetting).filter_by(key="notify_prefs_1_max_daily").first()
        row2 = db_session.query(UserSetting).filter_by(key="notify_prefs_2_max_daily").first()
        assert row1.value == "10"
        assert row2.value == "20"


class TestGetPreferredChannels:
    def test_returns_all_when_no_prefs(self, engine, db_session):
        channels = engine.get_preferred_channels(1)
        assert sorted(channels) == sorted(["telegram", "email", "web"])

    def test_returns_enabled_only(self, engine, db_session):
        db_session.add(ChannelPreference(user_id=1, channel="telegram", enabled=True))
        db_session.add(ChannelPreference(user_id=1, channel="email", enabled=False))
        db_session.commit()
        channels = engine.get_preferred_channels(1)
        assert "telegram" in channels
        assert "email" not in channels

    def test_empty_means_all(self, engine, db_session):
        channels = engine.get_preferred_channels(42)
        assert len(channels) == 3


class TestGetEffectiveThreshold:
    def test_conservative_lowers_threshold(self, engine, db_session):
        db_session.add(UserProfileModel(user_id=1, risk_profile="conservative"))
        db_session.commit()
        assert engine.get_effective_threshold(1, 100.0) == 100.0 * RISK_MULTIPLIERS["conservative"]

    def test_aggressive_raises_threshold(self, engine, db_session):
        db_session.add(UserProfileModel(user_id=1, risk_profile="aggressive"))
        db_session.commit()
        assert engine.get_effective_threshold(1, 100.0) == 100.0 * RISK_MULTIPLIERS["aggressive"]

    def test_balanced_default(self, engine, db_session):
        db_session.add(UserProfileModel(user_id=1, risk_profile="balanced"))
        db_session.commit()
        assert engine.get_effective_threshold(1, 100.0) == 100.0

    def test_no_profile_defaults_to_balanced(self, engine, db_session):
        assert engine.get_effective_threshold(999, 100.0) == 100.0

    def test_unknown_profile_defaults_to_balanced(self, engine, db_session):
        db_session.add(UserProfileModel(user_id=1, risk_profile="unknown"))
        db_session.commit()
        assert engine.get_effective_threshold(1, 100.0) == 100.0

    def test_near_zero_threshold(self, engine, db_session):
        db_session.add(UserProfileModel(user_id=1, risk_profile="conservative"))
        db_session.commit()
        assert engine.get_effective_threshold(1, 0.0) == 0.0

    def test_large_threshold(self, engine, db_session):
        db_session.add(UserProfileModel(user_id=1, risk_profile="aggressive"))
        db_session.commit()
        assert engine.get_effective_threshold(1, 1000.0) == 1300.0


# ── Integration with NotificationService ────────────────────────────────────


class TestIntegrationWithNotificationService:
    def test_save_notification_checks_prefs(self):
        mock_db = MagicMock()
        mock_prefs = MagicMock(spec=NotificationPreferencesEngine)
        mock_freq = MagicMock(spec=FrequencyController)
        mock_prefs.frequency = mock_freq
        mock_prefs.get_user_preferences.return_value = {
            "max_daily": 50,
            "quiet_hours": None,
        }
        mock_freq.allow_notification.return_value = False

        with patch("src.notifications.service.get_session", return_value=mock_db):
            from src.notifications.service import NotificationService

            svc = NotificationService(prefs_engine=mock_prefs)
            result = svc.save_notification(1, "signal", "test", title="SBER")

        assert result is False
        mock_freq.allow_notification.assert_called_once_with(
            user_id=1, notif_type="signal", ticker="SBER", max_daily=50, quiet_hours=None
        )
        mock_db.add.assert_not_called()

    def test_save_notification_records_when_allowed(self):
        mock_db = MagicMock()
        mock_prefs = MagicMock(spec=NotificationPreferencesEngine)
        mock_freq = MagicMock(spec=FrequencyController)
        mock_prefs.frequency = mock_freq
        mock_prefs.get_user_preferences.return_value = {
            "max_daily": 50,
            "quiet_hours": None,
        }
        mock_freq.allow_notification.return_value = True

        with patch("src.notifications.service.get_session", return_value=mock_db):
            from src.notifications.service import NotificationService

            svc = NotificationService(prefs_engine=mock_prefs)
            result = svc.save_notification(1, "signal", "test", title="SBER")

        assert result is True
        mock_freq.record_notification.assert_called_once_with(1, "signal", "SBER")
        mock_db.add.assert_called_once()

    def test_get_preferred_channels_delegates(self):
        mock_db = MagicMock()
        mock_prefs = MagicMock(spec=NotificationPreferencesEngine)
        mock_prefs.get_preferred_channels.return_value = ["telegram"]

        from src.notifications.service import NotificationService

        svc = NotificationService(prefs_engine=mock_prefs)
        channels = svc.get_preferred_channels(1)

        assert channels == ["telegram"]
        mock_prefs.get_preferred_channels.assert_called_once_with(1)

    def test_get_preferred_channels_default_when_no_engine(self):
        from src.notifications.service import NotificationService

        svc = NotificationService()
        channels = svc.get_preferred_channels(1)
        assert sorted(channels) == sorted(["telegram", "email", "web"])

    def test_save_notification_no_engine_passes_through(self):
        mock_db = MagicMock()

        with patch("src.notifications.service.get_session", return_value=mock_db):
            from src.notifications.service import NotificationService

            svc = NotificationService()
            result = svc.save_notification(1, "signal", "test")

        assert result is True
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_per_user_preferences_isolation_with_service(self):
        mock_db = MagicMock()
        mock_prefs = MagicMock(spec=NotificationPreferencesEngine)
        mock_freq = MagicMock(spec=FrequencyController)
        mock_prefs.frequency = mock_freq

        def side_effect(user_id, notif_type, ticker=None, max_daily=50, quiet_hours=None):
            return user_id == 1

        mock_freq.allow_notification.side_effect = side_effect
        mock_prefs.get_user_preferences.return_value = {"max_daily": 50, "quiet_hours": None}

        with patch("src.notifications.service.get_session", return_value=mock_db):
            from src.notifications.service import NotificationService

            svc = NotificationService(prefs_engine=mock_prefs)
            r1 = svc.save_notification(1, "signal", "test")
            r2 = svc.save_notification(2, "signal", "test")

        assert r1 is True
        assert r2 is False
