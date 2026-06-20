"""Tests for NotificationService"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.db.models import Dividend, GeoRiskScore, Instrument, Notification, Portfolio, Price, Subscription
from src.db.models import Signal as SignalModel
from src.notifications import (
    DailySummaryNotification,
    DividendNotification,
    GeoRiskNotification,
    PriceTargetAlert,
    RebalanceAlert,
    SignalNotification,
)
from src.notifications.service import NotificationService, _geo_level, format_daily_summary_text, format_signal_text


@pytest.fixture
def service() -> NotificationService:
    return NotificationService()


# ── _geo_level ────────────────────────────────────────────────────────────────


class TestGeoLevel:
    def test_low_below_3(self):
        assert _geo_level(0) == "LOW"
        assert _geo_level(2.9) == "LOW"

    def test_moderate_3_to_5(self):
        assert _geo_level(3) == "MODERATE"
        assert _geo_level(4.9) == "MODERATE"

    def test_high_5_to_7(self):
        assert _geo_level(5) == "HIGH"
        assert _geo_level(6.9) == "HIGH"

    def test_critical_7_and_above(self):
        assert _geo_level(7) == "CRITICAL"
        assert _geo_level(10) == "CRITICAL"


# ── format_signal_text ────────────────────────────────────────────────────────


class TestFormatSignalText:
    def test_buy_action(self):
        n = SignalNotification(
            ticker="SBER",
            action="BUY",
            prev_action=None,
            confidence=0.85,
            weighted_score=0.8,
            reasons=["хороший тренд", "сильный сигнал"],
            max_portfolio_pct=10,
        )
        text = format_signal_text(n)
        assert "SBER" in text
        assert "BUY" in text
        assert "🟢" in text

    def test_sell_action(self):
        n = SignalNotification(
            ticker="GAZP",
            action="SELL",
            prev_action=None,
            confidence=0.75,
            weighted_score=-0.6,
            reasons=["перегрев"],
            max_portfolio_pct=5,
        )
        text = format_signal_text(n)
        assert "GAZP" in text
        assert "SELL" in text
        assert "🔴" in text

    def test_action_change_indicator(self):
        n = SignalNotification(
            ticker="SBER",
            action="SELL",
            prev_action="BUY",
            confidence=0.9,
            weighted_score=-0.7,
            reasons=["смена тренда"],
            max_portfolio_pct=5,
        )
        text = format_signal_text(n)
        assert "Было" in text

    def test_reasons_limited_to_4(self):
        reasons = [f"r{i}" for i in range(10)]
        n = SignalNotification(
            ticker="T",
            action="HOLD",
            prev_action=None,
            confidence=0.5,
            weighted_score=0.0,
            reasons=reasons,
            max_portfolio_pct=10,
        )
        text = format_signal_text(n)
        assert text.count("•") <= 4

    def test_no_reasons(self):
        n = SignalNotification(
            ticker="T",
            action="NEUTRAL",
            prev_action=None,
            confidence=0.5,
            weighted_score=0.0,
            reasons=[],
            max_portfolio_pct=10,
        )
        text = format_signal_text(n)
        assert "⚪" in text
        assert "T" in text


# ── format_daily_summary_text ─────────────────────────────────────────────────


class TestFormatDailySummaryText:
    def test_basic_fields(self):
        n = DailySummaryNotification(
            date="2024-01-15",
            total_signals=10,
            buy_signals=5,
            sell_signals=2,
            geo_risk=3.5,
            portfolio_value=None,
            top_picks=[],
        )
        text = format_daily_summary_text(n)
        assert "2024-01-15" in text
        assert "10" in text
        assert "5" in text

    def test_with_top_picks(self):
        n = DailySummaryNotification(
            date="2024-01-15",
            total_signals=5,
            buy_signals=3,
            sell_signals=1,
            geo_risk=2.0,
            portfolio_value=None,
            top_picks=["SBER", "GAZP"],
        )
        text = format_daily_summary_text(n)
        assert "SBER" in text
        assert "GAZP" in text
        assert "🏆" in text

    def test_with_portfolio_value(self):
        n = DailySummaryNotification(
            date="2024-01-15",
            total_signals=3,
            buy_signals=2,
            sell_signals=0,
            geo_risk=1.0,
            portfolio_value=150000.0,
            top_picks=[],
        )
        text = format_daily_summary_text(n)
        assert "150" in text

    def test_no_optional_sections(self):
        n = DailySummaryNotification(
            date="2024-01-15",
            total_signals=0,
            buy_signals=0,
            sell_signals=0,
            geo_risk=0.0,
            portfolio_value=None,
            top_picks=[],
        )
        text = format_daily_summary_text(n)
        assert "🏆" not in text
        assert "💵" not in text


# ── subscribe ─────────────────────────────────────────────────────────────────


class TestSubscribe:
    def test_new_subscriber(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.subscribe(1, 12345, "signal")

        mock_db.add.assert_called_once()
        sub = mock_db.add.call_args[0][0]
        assert sub.user_id == 1
        assert sub.chat_id == 12345
        assert sub.notify_signal is True
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    def test_existing_subscriber_updates_flag(self, service):
        existing = MagicMock(spec=Subscription)
        existing.notify_signal = False
        existing.notify_daily = True

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = existing

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.subscribe(1, 12345, "signal")

        assert existing.notify_signal is True
        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    def test_invalid_notify_type_raises(self, service):
        with pytest.raises(ValueError, match="Invalid notify_type: bad"):
            service.subscribe(1, 12345, "bad")

    def test_rollback_on_error(self, service):
        existing = MagicMock(spec=Subscription)
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = existing
        mock_db.commit.side_effect = Exception("db failure")

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.subscribe(1, 12345, "daily")

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()

    def test_subscribe_defaults_to_daily(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.subscribe(1, 12345)

        assert mock_db.add.call_args[0][0].notify_daily is True


# ── unsubscribe ───────────────────────────────────────────────────────────────


class TestUnsubscribe:
    def test_unsubscribe_specific_type(self, service):
        existing = MagicMock(spec=Subscription)
        existing.notify_signal = True

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = existing

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.unsubscribe(1, "signal")

        assert existing.notify_signal is False
        mock_db.delete.assert_not_called()
        mock_db.commit.assert_called_once()

    def test_unsubscribe_all_removes_subscription(self, service):
        existing = MagicMock(spec=Subscription)

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = existing

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.unsubscribe(1)

        mock_db.delete.assert_called_once_with(existing)
        mock_db.commit.assert_called_once()

    def test_unsubscribe_no_existing(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.unsubscribe(1, "signal")

        mock_db.delete.assert_not_called()
        mock_db.commit.assert_not_called()
        mock_db.close.assert_called_once()

    def test_unsubscribe_invalid_type_raises(self, service):
        with pytest.raises(ValueError, match="Invalid notify_type: invalid"):
            service.unsubscribe(1, "invalid")

    def test_unsubscribe_rollback_on_error(self, service):
        existing = MagicMock(spec=Subscription)
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = existing
        mock_db.commit.side_effect = Exception("fail")

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.unsubscribe(1, "signal")

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()


# ── get_subscribers ───────────────────────────────────────────────────────────


class TestGetSubscribers:
    def test_returns_user_chat_pairs(self, service):
        row1 = MagicMock(user_id=1, chat_id=10)
        row2 = MagicMock(user_id=2, chat_id=20)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [row1, row2]

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_subscribers("signal")

        assert result == [(1, 10), (2, 20)]
        mock_db.close.assert_called_once()

    def test_returns_empty_when_no_subscribers(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_subscribers("daily")

        assert result == []

    def test_returns_empty_for_invalid_type(self, service):
        mock_db = MagicMock()
        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_subscribers("nonexistent")

        assert result == []
        mock_db.close.assert_called_once()


# ── save_notification ─────────────────────────────────────────────────────────


class TestSaveNotification:
    def test_saves_notification(self, service):
        mock_db = MagicMock()

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.save_notification(1, "signal", "test message", title="Test")

        mock_db.add.assert_called_once()
        n = mock_db.add.call_args[0][0]
        assert n.user_id == 1
        assert n.type == "signal"
        assert n.message == "test message"
        assert n.title == "Test"
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    def test_saves_with_data(self, service):
        mock_db = MagicMock()

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.save_notification(1, "geo", "msg", data={"key": "val"})

        assert mock_db.add.call_args[0][0].data_json == {"key": "val"}

    def test_rollback_on_error(self, service):
        mock_db = MagicMock()
        mock_db.commit.side_effect = Exception("fail")

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.save_notification(1, "geo", "msg")

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()


# ── was_signal_sent_today ─────────────────────────────────────────────────────


class TestWasSignalSentToday:
    def test_returns_true_when_sent(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.count.return_value = 1

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.was_signal_sent_today("SBER")

        assert result is True
        mock_db.close.assert_called_once()

    def test_returns_false_when_not_sent(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.was_signal_sent_today("GAZP")

        assert result is False
        mock_db.close.assert_called_once()


# ── get_unread_count ──────────────────────────────────────────────────────────


class TestGetUnreadCount:
    def test_returns_count(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.count.return_value = 5

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_unread_count(1)

        assert result == 5
        mock_db.close.assert_called_once()

    def test_returns_zero(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.count.return_value = 0

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_unread_count(99)

        assert result == 0


# ── mark_read ─────────────────────────────────────────────────────────────────


class TestMarkRead:
    def test_mark_all_read(self, service):
        mock_db = MagicMock()

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.mark_read(1)

        mock_db.query.return_value.filter_by.return_value.update.assert_called_once_with({"read": True})
        mock_db.commit.assert_called_once()

    def test_mark_specific_read(self, service):
        mock_db = MagicMock()

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.mark_read(1, notif_id=42)

        mock_db.query.return_value.filter_by.return_value.filter.assert_called_once()
        mock_db.query.return_value.filter_by.return_value.filter.return_value.update.assert_called_once_with(
            {"read": True},
        )
        mock_db.commit.assert_called_once()

    def test_rollback_on_error(self, service):
        mock_db = MagicMock()
        mock_db.commit.side_effect = Exception("fail")

        with patch("src.notifications.service.get_session", return_value=mock_db):
            service.mark_read(1)

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()


# ── get_signal_changes ────────────────────────────────────────────────────────
#
#   Code pattern:
#     db.query(Model).filter(...).order_by(...).all()
#     db.query(Model).filter(...).order_by(...).first()
#     db.query(Instrument).filter_by(id=...).first()
#   Note: .desc() is passed *as argument* to .order_by(), not chained.

class TestGetSignalChanges:
    def test_returns_signal_notifications(self, service):
        s1 = MagicMock(spec=SignalModel)
        s1.instrument_id = 1
        s1.action = "BUY"
        s1.confidence = 0.9
        s1.fused_json = {"weighted_score": 0.85, "reasons": ["тренд"], "max_portfolio_pct": 10}

        s2 = MagicMock(spec=SignalModel)
        s2.instrument_id = 2
        s2.action = "SELL"
        s2.confidence = 0.7
        s2.fused_json = {"weighted_score": -0.6, "reasons": ["перегрев"], "max_portfolio_pct": 5}

        inst1 = MagicMock(ticker="SBER")
        inst2 = MagicMock(ticker="GAZP")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [s1, s2]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.side_effect = [None, None]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst1, inst2]

        with (
            patch("src.notifications.service.get_session", return_value=mock_db),
            patch.object(NotificationService, "was_signal_sent_today", return_value=False),
        ):
            result = service.get_signal_changes()

        assert len(result) == 2
        assert result[0].ticker == "SBER"
        assert result[0].action == "BUY"
        assert result[0].confidence == 0.9
        assert result[1].ticker == "GAZP"
        assert result[1].action == "SELL"

    def test_skips_already_sent_signals(self, service):
        s = MagicMock(spec=SignalModel)
        s.instrument_id = 1
        s.action = "BUY"
        s.confidence = 0.8
        s.fused_json = {"weighted_score": 0.7, "reasons": [], "max_portfolio_pct": 10}

        inst = MagicMock(ticker="SBER")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [s]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst

        with (
            patch("src.notifications.service.get_session", return_value=mock_db),
            patch.object(NotificationService, "was_signal_sent_today", return_value=True),
        ):
            result = service.get_signal_changes()

        assert len(result) == 0

    def test_skips_signals_without_instrument(self, service):
        s = MagicMock(spec=SignalModel)
        s.instrument_id = 999
        s.action = "HOLD"
        s.confidence = 0.5
        s.fused_json = {}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [s]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with (
            patch("src.notifications.service.get_session", return_value=mock_db),
            patch.object(NotificationService, "was_signal_sent_today", return_value=False),
        ):
            result = service.get_signal_changes()

        assert len(result) == 0

    def test_empty_when_no_recent_signals(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_signal_changes()

        assert result == []

    def test_includes_prev_action(self, service):
        s = MagicMock(spec=SignalModel)
        s.instrument_id = 1
        s.action = "SELL"
        s.confidence = 0.8
        s.fused_json = {"weighted_score": -0.7, "reasons": ["разворот"], "max_portfolio_pct": 5}

        prev_s = MagicMock(spec=SignalModel)
        prev_s.action = "BUY"

        inst = MagicMock(ticker="SBER")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [s]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.side_effect = [prev_s]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst

        with (
            patch("src.notifications.service.get_session", return_value=mock_db),
            patch.object(NotificationService, "was_signal_sent_today", return_value=False),
        ):
            result = service.get_signal_changes()

        assert len(result) == 1
        assert result[0].prev_action == "BUY"


# ── get_geo_change ────────────────────────────────────────────────────────────
#
#   Code pattern:
#     db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
#   .desc() is passed as argument, not chained.

class TestGetGeoChange:
    def test_returns_geo_notification(self, service):
        today_score = MagicMock(spec=GeoRiskScore)
        today_score.date = date(2024, 6, 1)
        today_score.score = 6.5

        prev_score = MagicMock(spec=GeoRiskScore)
        prev_score.score = 4.0

        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.first.return_value = today_score
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = prev_score

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_geo_change()

        assert result is not None
        assert result.score == 6.5
        assert result.level == "HIGH"
        assert result.prev_score == 4.0

    def test_returns_none_when_no_geo_data(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_geo_change()

        assert result is None

    def test_handles_missing_prev_score(self, service):
        today_score = MagicMock(spec=GeoRiskScore)
        today_score.date = date(2024, 6, 1)
        today_score.score = 3.2

        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.first.return_value = today_score
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_geo_change()

        assert result is not None
        assert result.score == 3.2
        assert result.level == "MODERATE"
        assert result.prev_score is None

    def test_critical_level(self, service):
        today_score = MagicMock(spec=GeoRiskScore)
        today_score.date = date(2024, 6, 1)
        today_score.score = 8.0

        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.first.return_value = today_score
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_geo_change()

        assert result.level == "CRITICAL"


# ── get_upcoming_dividends ────────────────────────────────────────────────────
#
#   Code pattern:
#     db.query(Dividend).filter(...).order_by(...).all()
#     db.query(Instrument).filter_by(id=...).first()
#     db.query(Price).filter_by(instrument_id=...).order_by(Price.date.desc()).first()

class TestGetUpcomingDividends:
    def test_returns_dividend_notifications(self, service):
        d1 = MagicMock(spec=Dividend)
        d1.instrument_id = 1
        d1.amount = 50.0
        d1.date = date(2024, 7, 1)

        d2 = MagicMock(spec=Dividend)
        d2.instrument_id = 2
        d2.amount = 30.0
        d2.date = date(2024, 7, 15)

        inst1 = MagicMock(ticker="SBER")
        inst2 = MagicMock(ticker="GAZP")

        price1 = MagicMock(close=250.0)
        price2 = MagicMock(close=150.0)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [d1, d2]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst1, inst2]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.side_effect = [price1, price2]

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_upcoming_dividends(14)

        assert len(result) == 2
        assert result[0].ticker == "SBER"
        assert result[0].amount == 50.0
        assert result[0].yield_pct == pytest.approx(20.0)
        assert result[1].ticker == "GAZP"
        assert result[1].amount == 30.0
        assert result[1].yield_pct == pytest.approx(20.0)

    def test_skips_dividend_without_instrument(self, service):
        d = MagicMock(spec=Dividend)
        d.instrument_id = 999
        d.amount = 10.0
        d.date = date(2024, 7, 1)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [d]
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_upcoming_dividends(14)

        assert len(result) == 0

    def test_handles_missing_price(self, service):
        d = MagicMock(spec=Dividend)
        d.instrument_id = 1
        d.amount = 10.0
        d.date = date(2024, 7, 1)

        inst = MagicMock(ticker="SBER")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [d]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_upcoming_dividends(14)

        assert len(result) == 1
        assert result[0].ticker == "SBER"
        assert result[0].yield_pct is None

    def test_empty_when_no_upcoming(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_upcoming_dividends(30)

        assert result == []


# ── get_daily_summary ─────────────────────────────────────────────────────────
#
#   Code pattern:
#     db.query(SignalModel).filter(...).all()
#     db.query(GeoRiskScore).order_by(...).first()
#     db.query(SignalModel).filter(...).order_by(...).limit(3).all()
#     db.query(Instrument).filter_by(id=...).first()
#     db.query(Portfolio).all()
#     db.query(Price).filter_by(instrument_id=...).order_by(...).first()

class TestGetDailySummary:
    def test_returns_summary_with_all_fields(self, service):
        signal_buy = MagicMock(spec=SignalModel)
        signal_buy.action = "BUY"
        signal_buy.instrument_id = 1
        signal_buy.confidence = 0.9

        signal_cautious = MagicMock(spec=SignalModel)
        signal_cautious.action = "CAUTIOUS_BUY"
        signal_cautious.instrument_id = 2
        signal_cautious.confidence = 0.7

        signal_sell = MagicMock(spec=SignalModel)
        signal_sell.action = "SELL"
        signal_sell.instrument_id = 3
        signal_sell.confidence = 0.8

        geo_obj = MagicMock()
        geo_obj.score = 4.5

        inst_buy = MagicMock(ticker="SBER")
        inst_cautious = MagicMock(ticker="GAZP")

        pos = MagicMock(spec=Portfolio)
        pos.instrument_id = 1
        pos.quantity = 10

        price = MagicMock(close=200.0)

        mock_db = MagicMock()

        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [signal_buy, signal_cautious, signal_sell],
        ]

        mock_db.query.return_value.order_by.return_value.first.return_value = geo_obj

        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            signal_buy,
            signal_cautious,
        ]

        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst_buy, inst_cautious]

        mock_db.query.return_value.all.return_value = [pos]

        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_daily_summary()

        assert isinstance(result, DailySummaryNotification)
        assert result.total_signals == 3
        assert result.buy_signals == 2
        assert result.sell_signals == 1
        assert result.geo_risk == 4.5
        assert "SBER" in result.top_picks
        assert "GAZP" in result.top_picks
        assert result.portfolio_value == 2000.0

    def test_returns_summary_without_geo_and_value(self, service):
        mock_db = MagicMock()

        mock_db.query.return_value.filter.return_value.all.side_effect = [[], []]

        mock_db.query.return_value.order_by.return_value.first.return_value = None

        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        mock_db.query.return_value.all.return_value = []

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_daily_summary()

        assert result.total_signals == 0
        assert result.buy_signals == 0
        assert result.sell_signals == 0
        assert result.geo_risk == 0.0
        assert result.top_picks == []
        assert result.portfolio_value is None

    def test_handles_geo_with_value(self, service):
        mock_db = MagicMock()

        mock_db.query.return_value.filter.return_value.all.side_effect = [[], []]
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.all.return_value = []

        geo_obj = MagicMock()
        geo_obj.score = 7.0
        mock_db.query.return_value.order_by.return_value.first.return_value = geo_obj

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.get_daily_summary()

        assert result.geo_risk == 7.0


# ── check_price_targets ───────────────────────────────────────────────────────
#
#   Code pattern:
#     db.query(Portfolio).all()
#     db.query(Instrument).filter_by(id=...).first()
#     db.query(Price).filter_by(instrument_id=...).order_by(Price.date.desc()).first()

class TestCheckPriceTargets:
    def test_take_profit_alert(self, service):
        pos = MagicMock(spec=Portfolio)
        pos.instrument_id = 1
        pos.avg_price = 100.0
        pos.quantity = 10

        inst = MagicMock(ticker="SBER")
        price = MagicMock(close=130.0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [pos]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.check_price_targets()

        assert len(result) == 1
        assert result[0].ticker == "SBER"
        assert result[0].target_type == "take_profit"
        assert result[0].current_price == 130.0
        assert result[0].triggered_pct == 30.0

    def test_stop_loss_alert(self, service):
        pos = MagicMock(spec=Portfolio)
        pos.instrument_id = 1
        pos.avg_price = 100.0
        pos.quantity = 5

        inst = MagicMock(ticker="GAZP")
        price = MagicMock(close=80.0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [pos]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.check_price_targets()

        assert len(result) == 1
        assert result[0].ticker == "GAZP"
        assert result[0].target_type == "stop_loss"
        assert result[0].triggered_pct == -20.0

    def test_no_alert_within_bounds(self, service):
        pos = MagicMock(spec=Portfolio)
        pos.instrument_id = 1
        pos.avg_price = 100.0
        pos.quantity = 1

        inst = MagicMock(ticker="SBER")
        price = MagicMock(close=110.0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [pos]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.check_price_targets()

        assert len(result) == 0

    def test_skips_position_without_instrument(self, service):
        pos = MagicMock(spec=Portfolio)
        pos.instrument_id = 999
        pos.avg_price = 100.0
        pos.quantity = 1

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [pos]
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.check_price_targets()

        assert len(result) == 0

    def test_skips_position_without_price(self, service):
        pos = MagicMock(spec=Portfolio)
        pos.instrument_id = 1
        pos.avg_price = 100.0
        pos.quantity = 1

        inst = MagicMock(ticker="SBER")

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [pos]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.check_price_targets()

        assert len(result) == 0

    def test_skips_position_with_zero_avg_price(self, service):
        pos = MagicMock(spec=Portfolio)
        pos.instrument_id = 1
        pos.avg_price = 0.0
        pos.quantity = 1

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [pos]

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.check_price_targets()

        assert len(result) == 0

    def test_returns_empty_when_no_positions(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = []

        with patch("src.notifications.service.get_session", return_value=mock_db):
            result = service.check_price_targets()

        assert result == []


# ── check_divergence ──────────────────────────────────────────────────────────
#
#   numpy is imported inside the method as `import numpy as np`.
#   Patch numpy.polyfit at the module level.

class TestCheckDivergence:
    # Helper: 20 values for price/rsi, 10 for macd
    @staticmethod
    def _trend(start, end, count):
        return [float(start + (end - start) * i / (count - 1)) for i in range(count)]

    def test_bearish_rsi_divergence(self, service):
        prices = self._trend(100, 120, 20)
        rsi_values = self._trend(70, 50, 20)
        macd_values = [0.0] * 10

        with patch("numpy.polyfit") as mock_polyfit:
            mock_polyfit.side_effect = [
                [1.0, 0],
                [-1.5, 0],
                [0.0, 0],
            ]
            result = service.check_divergence("SBER", prices, rsi_values, macd_values)

        assert len(result) == 1
        assert result[0].divergence_type == "bearish"
        assert result[0].indicator == "rsi"
        assert result[0].ticker == "SBER"

    def test_bullish_rsi_divergence(self, service):
        prices = self._trend(120, 100, 20)
        rsi_values = self._trend(30, 55, 20)
        macd_values = [0.0] * 10

        with patch("numpy.polyfit") as mock_polyfit:
            mock_polyfit.side_effect = [
                [-1.0, 0],
                [1.5, 0],
                [0.0, 0],
            ]
            result = service.check_divergence("GAZP", prices, rsi_values, macd_values)

        assert len(result) == 1
        assert result[0].divergence_type == "bullish"
        assert result[0].indicator == "rsi"

    def test_bearish_macd_divergence(self, service):
        prices = self._trend(100, 120, 20)
        rsi_values = [50.0] * 20
        macd_values = self._trend(5, -5, 10)

        with patch("numpy.polyfit") as mock_polyfit:
            mock_polyfit.side_effect = [
                [1.0, 0],
                [0.0, 0],
                [-1.0, 0],
            ]
            result = service.check_divergence("SBER", prices, rsi_values, macd_values)

        assert len(result) == 1
        assert result[0].divergence_type == "bearish"
        assert result[0].indicator == "macd"

    def test_bullish_macd_divergence(self, service):
        prices = self._trend(120, 100, 20)
        rsi_values = [50.0] * 20
        macd_values = self._trend(-5, 5, 10)

        with patch("numpy.polyfit") as mock_polyfit:
            mock_polyfit.side_effect = [
                [-1.0, 0],
                [0.0, 0],
                [1.0, 0],
            ]
            result = service.check_divergence("GAZP", prices, rsi_values, macd_values)

        assert len(result) == 1
        assert result[0].divergence_type == "bullish"
        assert result[0].indicator == "macd"

    def test_both_rsi_and_macd_divergence(self, service):
        prices = self._trend(100, 120, 20)
        rsi_values = self._trend(70, 50, 20)
        macd_values = self._trend(5, -5, 10)

        with patch("numpy.polyfit") as mock_polyfit:
            mock_polyfit.side_effect = [
                [1.0, 0],
                [-1.5, 0],
                [-1.0, 0],
            ]
            result = service.check_divergence("SBER", prices, rsi_values, macd_values)

        assert len(result) == 2

    def test_returns_empty_when_no_divergence(self, service):
        prices = self._trend(100, 120, 20)
        rsi_values = [50.0] * 20
        macd_values = [0.0] * 10

        with patch("numpy.polyfit") as mock_polyfit:
            mock_polyfit.side_effect = [
                [1.0, 0],
                [1.0, 0],
                [0.0, 0],
            ]
            result = service.check_divergence("SBER", prices, rsi_values, macd_values)

        assert len(result) == 0

    def test_returns_empty_with_insufficient_data(self, service):
        result = service.check_divergence("SBER", [1, 2, 3], [1, 2, 3], [1, 2, 3])
        assert result == []

    def test_rsi_trend_not_strong_enough(self, service):
        prices = self._trend(100, 120, 20)
        rsi_values = [50.0] * 20
        macd_values = [0.0] * 10

        with patch("numpy.polyfit") as mock_polyfit:
            mock_polyfit.side_effect = [
                [1.0, 0],
                [-0.05, 0],
                [0.0, 0],
            ]
            result = service.check_divergence("SBER", prices, rsi_values, macd_values)

        assert len(result) == 0

    def test_macd_trend_not_strong_enough(self, service):
        prices = self._trend(100, 120, 20)
        rsi_values = [50.0] * 20
        macd_values = [0.0] * 10

        with patch("numpy.polyfit") as mock_polyfit:
            mock_polyfit.side_effect = [
                [1.0, 0],
                [0.0, 0],
                [-0.04, 0],
            ]
            result = service.check_divergence("SBER", prices, rsi_values, macd_values)

        assert len(result) == 0


# ── check_rebalance ───────────────────────────────────────────────────────────
#
#   Takes an explicit db Session argument.  Uses import inside method:
#     from src.user_profile import profile_manager

class TestCheckRebalance:
    def test_returns_alert_when_exceeds_threshold(self, service):
        inst = MagicMock(id=1, ticker="SBER")
        pos = MagicMock(instrument_id=1, quantity=10)
        price = MagicMock(close=200.0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[inst], [pos]]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price

        with patch("src.user_profile.profile_manager.get_max_position", return_value=10):
            result = service.check_rebalance(mock_db)

        assert len(result) == 1
        assert result[0].ticker == "SBER"
        assert result[0].current_pct == pytest.approx(100.0)
        assert result[0].target_pct == 10.0
        assert result[0].deviation_pct == pytest.approx(90.0)
        assert "превышает" in result[0].reason

    def test_no_alert_when_within_threshold(self, service):
        inst1 = MagicMock(id=1, ticker="A")
        inst2 = MagicMock(id=2, ticker="B")
        inst3 = MagicMock(id=3, ticker="C")

        pos1 = MagicMock(instrument_id=1, quantity=1)
        pos2 = MagicMock(instrument_id=2, quantity=1)
        pos3 = MagicMock(instrument_id=3, quantity=1)

        price = MagicMock(close=100.0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[inst1, inst2, inst3], [pos1, pos2, pos3]]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst1, inst2, inst3]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.side_effect = [price, price, price]

        with patch("src.user_profile.profile_manager.get_max_position", return_value=30):
            result = service.check_rebalance(mock_db)

        assert len(result) == 0

    def test_returns_empty_when_no_positions(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[], []]

        result = service.check_rebalance(mock_db)

        assert result == []

    def test_returns_empty_when_total_value_zero(self, service):
        inst = MagicMock(id=1, ticker="SBER")
        pos = MagicMock(instrument_id=1, quantity=0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[inst], [pos]]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

        result = service.check_rebalance(mock_db)

        assert result == []

    def test_multiple_positions_multiple_alerts(self, service):
        inst1 = MagicMock(id=1, ticker="SBER")
        inst2 = MagicMock(id=2, ticker="GAZP")

        pos1 = MagicMock(instrument_id=1, quantity=10)
        pos2 = MagicMock(instrument_id=2, quantity=10)

        price = MagicMock(close=100.0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[inst1, inst2], [pos1, pos2]]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst1, inst2]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.side_effect = [price, price]

        with patch("src.user_profile.profile_manager.get_max_position", return_value=10):
            result = service.check_rebalance(mock_db)

        assert len(result) == 2
        assert result[0].ticker == "SBER"
        assert result[1].ticker == "GAZP"

    def test_skips_position_without_price(self, service):
        inst = MagicMock(id=1, ticker="SBER")
        pos = MagicMock(instrument_id=1, quantity=10)

        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[inst], [pos]]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

        with patch("src.user_profile.profile_manager.get_max_position", return_value=10):
            result = service.check_rebalance(mock_db)

        assert len(result) == 0

    def test_only_alerts_when_pct_exceeds_130pct_of_max(self, service):
        inst = MagicMock(id=1, ticker="SBER")
        pos = MagicMock(instrument_id=1, quantity=10)
        price = MagicMock(close=100.0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[inst], [pos]]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price

        with patch("src.user_profile.profile_manager.get_max_position", return_value=30):
            result = service.check_rebalance(mock_db)

        assert len(result) == 1


# ── check_rebalance_async ─────────────────────────────────────────────────────

class TestCheckRebalanceAsync:
    def test_delegates_to_check_rebalance(self, service):
        inst = MagicMock(id=1, ticker="SBER")
        pos = MagicMock(instrument_id=1, quantity=10)
        price = MagicMock(close=200.0)

        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[inst], [pos]]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price

        with patch("src.user_profile.profile_manager.get_max_position", return_value=10):
            result = service.check_rebalance_async(mock_db)

        assert len(result) == 1
        assert result[0].ticker == "SBER"

    def test_returns_empty_when_delegate_returns_empty(self, service):
        mock_db = MagicMock()
        mock_db.query.return_value.all.side_effect = [[], []]

        result = service.check_rebalance_async(mock_db)

        assert result == []
