from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.alerts.history import AlertHistory
from src.alerts.preferences import UserAlertPreferences
from src.alerts.prioritizer import AlertAggregator
from src.alerts.push import AlertPushService
from src.db.models import AlertLog, MutedAlert


class TestAlertAnalytics:
    def test_analytics_empty(self):
        history = AlertHistory()
        result = history.get_analytics(days=30)
        assert result["total"] == 0
        assert result["by_type"] == {}
        assert result["top_tickers"] == []

    def test_analytics_with_data(self):
        history = AlertHistory()
        history._memory = [
            {"timestamp": "2026-06-30T10:00:00", "type": "HIGH", "ticker": "SBER", "severity": 0.8, "user_id": 1, "read": False, "title": "a", "message": "a"},
            {"timestamp": "2026-06-29T10:00:00", "type": "MEDIUM", "ticker": "GAZP", "severity": 0.5, "user_id": 1, "read": True, "title": "b", "message": "b"},
            {"timestamp": "2026-06-28T10:00:00", "type": "LOW", "ticker": "SBER", "severity": 0.2, "user_id": 1, "read": False, "title": "c", "message": "c"},
        ]
        result = history.get_analytics(days=30)
        assert result["total"] == 3
        assert result["by_type"] == {"HIGH": 1, "MEDIUM": 1, "LOW": 1}
        assert result["by_severity"] == {"low": 1, "medium": 1, "high": 1}
        assert result["read_count"] == 1
        assert result["unread_count"] == 2
        assert result["by_day"] == {"2026-06-30": 1, "2026-06-29": 1, "2026-06-28": 1}
        assert len(result["top_tickers"]) == 2
        assert result["top_tickers"][0]["ticker"] == "SBER"

    def test_analytics_filter_older_than_days(self):
        history = AlertHistory()
        history._memory = [
            {"timestamp": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(), "type": "HIGH", "ticker": "SBER", "severity": 0.8, "user_id": 1, "read": False, "title": "a", "message": "a"},
            {"timestamp": (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(), "type": "LOW", "ticker": "GAZP", "severity": 0.2, "user_id": 1, "read": False, "title": "b", "message": "b"},
        ]
        result = history.get_analytics(days=30)
        assert result["total"] == 1
        assert result["top_tickers"][0]["ticker"] == "SBER"

    def test_analytics_filter_by_user_id(self):
        history = AlertHistory()
        history._memory = [
            {"timestamp": "2026-06-30T10:00:00", "type": "HIGH", "ticker": "SBER", "severity": 0.8, "user_id": 1, "read": False, "title": "a", "message": "a"},
            {"timestamp": "2026-06-29T10:00:00", "type": "MEDIUM", "ticker": "GAZP", "severity": 0.5, "user_id": 2, "read": True, "title": "b", "message": "b"},
        ]
        result = history.get_analytics(days=30, user_id=1)
        assert result["total"] == 1
        assert result["top_tickers"][0]["ticker"] == "SBER"

    def test_analytics_avg_severity(self):
        history = AlertHistory()
        history._memory = [
            {"timestamp": "2026-06-30T10:00:00", "type": "LOW", "ticker": "SBER", "severity": 0.2, "user_id": 1, "read": False, "title": "a", "message": "a"},
            {"timestamp": "2026-06-29T10:00:00", "type": "HIGH", "ticker": "GAZP", "severity": 0.8, "user_id": 1, "read": False, "title": "b", "message": "b"},
        ]
        result = history.get_analytics(days=30)
        assert result["avg_severity"] == 0.5


class TestAlertHistory:
    def test_log_alert_memory(self):
        hist = AlertHistory()
        hist.log_alert({
            "ticker": "SBER", "priority": "HIGH",
            "priority_score": 0.8, "reason": "anomaly",
        })
        recent = hist.get_recent(days=1)
        assert len(recent) == 1
        assert recent[0]["ticker"] == "SBER"
        assert recent[0]["type"] == "HIGH"
        assert recent[0]["severity"] == 0.8

    def test_log_alert_with_db(self):
        mock_db = MagicMock()
        hist = AlertHistory(db=mock_db)
        hist.log_alert({
            "ticker": "GAZP", "priority": "CRITICAL",
            "title": "Risk", "reason": "sanctions",
        })
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, AlertLog)
        assert added.ticker == "GAZP"
        assert added.alert_type == "CRITICAL"
        mock_db.commit.assert_called_once()

    def test_log_alert_db_rollback(self):
        mock_db = MagicMock()
        mock_db.commit.side_effect = Exception("DB error")
        hist = AlertHistory(db=mock_db)
        hist.log_alert({
            "ticker": "SBER", "priority": "LOW", "priority_score": 0.1,
        })
        mock_db.rollback.assert_called_once()
        recent = hist.get_recent(days=1)
        assert len(recent) == 1

    def test_log_alert_json(self, tmp_path):
        json_file = tmp_path / "alerts.json"
        hist = AlertHistory(json_path=json_file)
        hist.log_alert({"ticker": "SBER", "priority": "MEDIUM", "reason": "test"})
        assert json_file.exists()
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["ticker"] == "SBER"

    def test_get_recent_filters(self):
        hist = AlertHistory()
        now = datetime.now(timezone.utc)
        hist._memory = [
            {"timestamp": (now - timedelta(hours=1)).isoformat(),
             "ticker": "SBER", "type": "HIGH", "severity": 0.8, "message": ""},
            {"timestamp": (now - timedelta(hours=2)).isoformat(),
             "ticker": "GAZP", "type": "MEDIUM", "severity": 0.5, "message": ""},
            {"timestamp": (now - timedelta(days=10)).isoformat(),
             "ticker": "SBER", "type": "LOW", "severity": 0.2, "message": ""},
        ]
        all_recent = hist.get_recent(days=7)
        assert len(all_recent) == 2
        sber = hist.get_recent(days=7, ticker="SBER")
        assert len(sber) == 1
        high = hist.get_recent(days=7, alert_type="HIGH")
        assert len(high) == 1

    def test_get_recent_with_db(self):
        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter2 = mock_filter.filter.return_value
        mock_filter2.order_by.return_value.all.return_value = [
            MagicMock(
                id=1, ticker="SBER", alert_type="HIGH", severity=0.8,
                title="Test", message="msg",
                created_at=datetime.now(timezone.utc),
                read=False, user_id=None,
            ),
        ]
        hist = AlertHistory(db=mock_db)
        results = hist.get_recent(days=3, ticker="SBER")
        assert len(results) == 1
        assert results[0]["ticker"] == "SBER"

    def test_get_stats_memory(self):
        hist = AlertHistory()
        now = datetime.now(timezone.utc)
        hist._memory = [
            {"timestamp": (now - timedelta(hours=1)).isoformat(),
             "ticker": "SBER", "type": "HIGH", "severity": 0.8, "message": ""},
            {"timestamp": (now - timedelta(hours=2)).isoformat(),
             "ticker": "GAZP", "type": "MEDIUM", "severity": 0.5, "message": ""},
            {"timestamp": (now - timedelta(hours=3)).isoformat(),
             "ticker": "SBER", "type": "HIGH", "severity": 0.9, "message": ""},
        ]
        stats = hist.get_stats(days=7)
        assert stats["total"] == 3
        assert stats["by_type"]["HIGH"] == 2
        assert stats["by_type"]["MEDIUM"] == 1


class TestAlertAggregator:
    def test_aggregate_empty(self):
        agg = AlertAggregator()
        result = agg.aggregate([])
        assert result["count"] == 0
        assert result["summary"] == "No alerts"

    def test_aggregate_groups_by_category_ticker(self):
        agg = AlertAggregator(window_minutes=60)
        now = datetime.now(timezone.utc)
        alerts = [
            {"category": "COMPANY", "ticker": "SBER", "timestamp": now.isoformat()},
            {"category": "COMPANY", "ticker": "SBER",
             "timestamp": (now - timedelta(minutes=5)).isoformat()},
            {"category": "COMPANY", "ticker": "SBER",
             "timestamp": (now - timedelta(minutes=10)).isoformat()},
            {"category": "GEOPOLITICAL", "ticker": "GAZP",
             "timestamp": now.isoformat()},
        ]
        result = agg.aggregate(alerts)
        assert result["count"] == 4
        assert "3 COMPANY alerts about SBER" in result["summary"]
        assert "1 GEOPOLITICAL alerts about GAZP" in result["summary"]

    def test_aggregate_respects_window(self):
        agg = AlertAggregator(window_minutes=30)
        now = datetime.now(timezone.utc)
        alerts = [
            {"category": "COMPANY", "ticker": "SBER", "timestamp": now.isoformat()},
            {"category": "COMPANY", "ticker": "SBER",
             "timestamp": (now - timedelta(minutes=45)).isoformat()},
        ]
        result = agg.aggregate(alerts)
        assert result["count"] == 1

    def test_aggregate_summary_format(self):
        agg = AlertAggregator(window_minutes=60)
        now = datetime.now(timezone.utc)
        alerts = [
            {"category": "MACRO", "ticker": "USD/RUB", "timestamp": now.isoformat()},
            {"category": "MACRO", "ticker": "USD/RUB",
             "timestamp": (now - timedelta(minutes=1)).isoformat()},
        ]
        result = agg.aggregate(alerts)
        assert result["summary"] == "2 MACRO alerts about USD/RUB"
        assert result["count"] == 2

    def test_aggregate_no_timestamp_field(self):
        agg = AlertAggregator(window_minutes=60)
        alerts = [
            {"category": "COMPANY", "ticker": "SBER"},
            {"category": "COMPANY", "ticker": "SBER"},
        ]
        result = agg.aggregate(alerts)
        assert result["count"] == 2


class TestUserAlertPreferences:
    def test_default_preferences(self):
        prefs = UserAlertPreferences()
        p = prefs.get_preferences(user_id=1)
        assert p["min_severity"] == "LOW"
        assert p["muted_tickers"] == []
        assert p["quiet_hours_start"] is None

    def test_get_preferences_cached(self):
        prefs = UserAlertPreferences()
        p1 = prefs.get_preferences(user_id=1)
        p2 = prefs.get_preferences(user_id=1)
        assert p1 is p2

    def test_filter_below_threshold(self):
        prefs = UserAlertPreferences()
        alerts = [
            {"ticker": "SBER", "priority": "LOW", "severity": 0.2},
            {"ticker": "SBER", "priority": "MEDIUM", "severity": 0.5},
            {"ticker": "SBER", "priority": "HIGH", "severity": 0.7},
        ]
        filtered = prefs.filter_alerts(
            alerts, {"min_severity": "MEDIUM", "muted_tickers": []},
        )
        assert len(filtered) == 2
        assert filtered[0]["priority"] == "MEDIUM"
        assert filtered[1]["priority"] == "HIGH"

    def test_filter_muted_tickers(self):
        prefs = UserAlertPreferences()
        alerts = [
            {"ticker": "SBER", "priority": "HIGH"},
            {"ticker": "GAZP", "priority": "CRITICAL"},
        ]
        filtered = prefs.filter_alerts(
            alerts, {"min_severity": "LOW", "muted_tickers": ["SBER"]},
        )
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "GAZP"

    def test_filter_quiet_hours_blocks_non_critical(self):
        prefs = UserAlertPreferences()
        now = datetime.now(timezone.utc)
        with patch("src.alerts.preferences.datetime") as mock_dt:
            mock_dt.now.return_value = now.replace(hour=23, minute=0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            alerts = [
                {"ticker": "SBER", "priority": "HIGH"},
                {"ticker": "GAZP", "priority": "CRITICAL"},
            ]
            filtered = prefs.filter_alerts(alerts, {
                "min_severity": "LOW",
                "muted_tickers": [],
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "08:00",
            })
            assert len(filtered) == 1
            assert filtered[0]["ticker"] == "GAZP"

    def test_filter_by_severity_numeric(self):
        prefs = UserAlertPreferences()
        alerts = [
            {"ticker": "SBER", "severity": 0.3},
            {"ticker": "SBER", "severity": 0.5},
            {"ticker": "SBER", "severity": 0.9},
        ]
        filtered = prefs.filter_alerts(
            alerts, {"min_severity": "MEDIUM", "muted_tickers": []},
        )
        assert len(filtered) == 2

    def test_clear_cache(self):
        prefs = UserAlertPreferences()
        prefs.get_preferences(user_id=1)
        assert 1 in prefs._db_preferences
        prefs.clear_cache(user_id=1)
        assert 1 not in prefs._db_preferences


class TestMutedAlert:
    def test_mute_ticker_adds_to_db(self, db_session):
        prefs = UserAlertPreferences()
        ok = prefs.mute_ticker(1, "SBER", db_session=db_session)
        assert ok is True
        row = db_session.query(MutedAlert).filter_by(user_id=1, ticker="SBER").first()
        assert row is not None

    def test_mute_ticker_idempotent(self, db_session):
        prefs = UserAlertPreferences()
        prefs.mute_ticker(1, "SBER", db_session=db_session)
        ok = prefs.mute_ticker(1, "SBER", db_session=db_session)
        assert ok is False

    def test_mute_ticker_uppercases(self, db_session):
        prefs = UserAlertPreferences()
        prefs.mute_ticker(1, "sber", db_session=db_session)
        row = db_session.query(MutedAlert).filter_by(user_id=1, ticker="SBER").first()
        assert row is not None

    def test_unmute_ticker_removes(self, db_session):
        prefs = UserAlertPreferences()
        prefs.mute_ticker(1, "SBER", db_session=db_session)
        ok = prefs.unmute_ticker(1, "SBER", db_session=db_session)
        assert ok is True
        row = db_session.query(MutedAlert).filter_by(user_id=1, ticker="SBER").first()
        assert row is None

    def test_unmute_nonexistent_returns_false(self, db_session):
        prefs = UserAlertPreferences()
        ok = prefs.unmute_ticker(1, "SBER", db_session=db_session)
        assert ok is False

    def test_get_muted_tickers(self, db_session):
        prefs = UserAlertPreferences()
        prefs.mute_ticker(1, "SBER", db_session=db_session)
        prefs.mute_ticker(1, "GAZP", db_session=db_session)
        tickers = prefs.get_muted_tickers(1, db_session=db_session)
        assert sorted(tickers) == ["GAZP", "SBER"]

    def test_get_muted_tickers_empty(self, db_session):
        prefs = UserAlertPreferences()
        tickers = prefs.get_muted_tickers(999, db_session=db_session)
        assert tickers == []

    def test_muted_tickers_appear_in_preferences(self, db_session):
        prefs = UserAlertPreferences()
        prefs.mute_ticker(1, "SBER", db_session=db_session)
        p = prefs.get_preferences(1, db_session=db_session)
        assert "SBER" in p["muted_tickers"]

    def test_set_preferences_persists(self, db_session):
        prefs = UserAlertPreferences()
        prefs.set_preferences(1, db_session=db_session, min_severity="HIGH")
        p = prefs.get_preferences(1, db_session=db_session)
        assert p["min_severity"] == "HIGH"

    def test_set_preferences_quiet_hours(self, db_session):
        prefs = UserAlertPreferences()
        prefs.set_preferences(1, db_session=db_session, quiet_hours_start="22:00", quiet_hours_end="08:00")
        p = prefs.get_preferences(1, db_session=db_session)
        assert p["quiet_hours_start"] == "22:00"
        assert p["quiet_hours_end"] == "08:00"

    def test_set_preferences_clear_quiet_hours(self, db_session):
        prefs = UserAlertPreferences()
        prefs.set_preferences(1, db_session=db_session, quiet_hours_start="22:00", quiet_hours_end="08:00")
        prefs.set_preferences(1, db_session=db_session, quiet_hours_start=None, quiet_hours_end=None)
        p = prefs.get_preferences(1, db_session=db_session)
        assert p["quiet_hours_start"] is None
        assert p["quiet_hours_end"] is None

    def test_mute_without_db_session_returns_false(self):
        prefs = UserAlertPreferences()
        ok = prefs.mute_ticker(1, "SBER")
        assert ok is False

    def test_set_preferences_without_db_does_not_crash(self):
        prefs = UserAlertPreferences()
        prefs.set_preferences(1, min_severity="HIGH")


class TestAlertPushService:
    def test_subscribe_unsubscribe(self):
        svc = AlertPushService()
        svc.subscribe("client_1")
        assert "client_1" in svc._subscribers
        svc.unsubscribe("client_1")
        assert "client_1" not in svc._subscribers

    def test_publish_calls_handler(self):
        svc = AlertPushService()
        handler = MagicMock()
        svc._subscribers["client_1"] = handler
        alert = {"ticker": "SBER", "reason": "test"}
        svc.publish(alert)
        handler.assert_called_once_with(alert)

    def test_publish_logs_message(self, caplog):
        svc = AlertPushService()
        svc.subscribe("client_1")
        with caplog.at_level(logging.INFO):
            svc.publish({"ticker": "SBER", "reason": "anomaly detected"})
        assert "publishing alert for SBER" in caplog.text

    def test_broadcast_sends_to_all(self):
        svc = AlertPushService()
        h1 = MagicMock()
        h2 = MagicMock()
        svc._subscribers["c1"] = h1
        svc._subscribers["c2"] = h2
        alerts = [
            {"ticker": "SBER", "reason": "a1"},
            {"ticker": "GAZP", "reason": "a2"},
        ]
        svc.broadcast(alerts)
        assert h1.call_count == 2
        assert h2.call_count == 2

    def test_publish_handler_exception_does_not_propagate(self):
        svc = AlertPushService()
        failing = MagicMock(side_effect=RuntimeError("fail"))
        working = MagicMock()
        svc._subscribers["f"] = failing
        svc._subscribers["w"] = working
        svc.publish({"ticker": "SBER"})
        working.assert_called_once()
