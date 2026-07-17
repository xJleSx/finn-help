"""Tests for bond signal generation and alert generators."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from src.alerts.generators import (
    generate_bond_coupon_alerts,
    generate_bond_rating_alerts,
    generate_bond_spread_alerts,
)
from src.analysis.signals.bond_signals import analyze_bond


class TestBondSignalAnalysis:
    def test_no_offering_returns_neutral(self):
        result = analyze_bond(None)
        assert result["action"] == "NEUTRAL"
        assert result["score"] == 0.0
        assert "Нет данных" in result["reasons"][0]

    def test_high_yield_buy_signal(self):
        offering = {
            "yield_to_maturity": 18.5,
            "coupon_rate": 12.0,
            "credit_rating": "AAA",
            "duration_years": 3.5,
            "coupon_type": "fixed",
        }
        result = analyze_bond(offering, key_rate=7.5, ofz_yield=10.0)
        assert result["action"] in ("BUY", "CAUTIOUS_BUY")
        assert result["score"] > 0
        assert "AAA" in str(result["reasons"])
        assert "спред" in str(result["reasons"]).lower()

    def test_low_rating_sell_signal(self):
        offering = {
            "yield_to_maturity": 30.0,
            "coupon_rate": 5.0,
            "credit_rating": "B",
            "duration_years": 8.0,
        }
        result = analyze_bond(offering, key_rate=7.5)
        assert result["action"] == "SELL"
        assert result["score"] < 0
        assert "Низкий кредитный рейтинг" in str(result["reasons"])
        assert "дефолт" in str(result["reasons"]).lower()

    def test_ofz_premium(self):
        offering = {
            "yield_to_maturity": 11.0,
            "coupon_rate": 10.0,
            "credit_rating": "AAA",
            "duration_years": 2.0,
        }
        result = analyze_bond(offering, key_rate=7.5, ofz_yield=12.0)
        assert result["score"] > 0
        assert "качественная" in str(result["reasons"]).lower()

    def test_ammortization_bonus(self):
        offering = {
            "yield_to_maturity": 12.0,
            "coupon_rate": 12.0,
            "credit_rating": "A",
            "has_amortization": True,
        }
        result = analyze_bond(offering, key_rate=7.5)
        assert "амортизация" in str(result["reasons"]).lower()
        assert result["score"] > 0

    def test_float_coupon_bonus(self):
        offering = {
            "yield_to_maturity": 12.0,
            "coupon_rate": 12.0,
            "credit_rating": "AA",
            "coupon_type": "float",
        }
        result = analyze_bond(offering, key_rate=7.5)
        assert "Плавающий купон" in str(result["reasons"])
        assert result["score"] > 0

    def test_extreme_duration_penalty(self):
        offering = {
            "yield_to_maturity": 12.0,
            "coupon_rate": 12.0,
            "credit_rating": "BBB+",
            "duration_years": 12.0,
        }
        result = analyze_bond(offering)
        assert "Большая дюрация" in str(result["reasons"])
        assert result["score"] < 0


class TestBondCouponAlerts:
    def test_no_schedule_no_alerts(self):
        db = MagicMock()
        db.query().join().filter().order_by().all.return_value = []
        alerts = generate_bond_coupon_alerts(db)
        assert alerts == []

    def test_upcoming_coupon_alert(self):
        db = MagicMock()
        mock_schedule = MagicMock()
        mock_schedule.coupon_date = date.today() + timedelta(days=5)
        mock_schedule.coupon_value = 42.5
        mock_ticker = "SU26238"
        db.query().join().filter().order_by().all.return_value = [(mock_schedule, mock_ticker)]

        alerts = generate_bond_coupon_alerts(db, days_ahead=14)
        assert len(alerts) == 1
        assert alerts[0]["ticker"] == "SU26238"
        assert alerts[0]["alert_type"] == "bond_coupon"
        assert "42.50" in alerts[0]["message"]


class TestBondRatingAlerts:
    def test_no_alerts_for_high_rating(self):
        db = MagicMock()
        mock_offering = MagicMock()
        mock_offering.credit_rating = "AAA"
        mock_offering.yield_to_maturity = 10.0
        mock_ticker = "SU26238"
        db.query().join().filter().all.return_value = [(mock_offering, mock_ticker)]

        alerts = generate_bond_rating_alerts(db)
        assert alerts == []

    def test_alert_for_low_rating(self):
        db = MagicMock()
        mock_offering = MagicMock()
        mock_offering.credit_rating = "B+"
        mock_offering.yield_to_maturity = 25.0
        mock_ticker = "RISKY01"
        db.query().join().filter().all.return_value = [(mock_offering, mock_ticker)]

        alerts = generate_bond_rating_alerts(db)
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "bond_rating_change"
        assert "B+" in alerts[0]["title"]


class TestBondSpreadAlerts:
    def test_no_alert_when_no_key_rate(self, monkeypatch):
        monkeypatch.setattr("src.collectors.macro.get_latest_key_rate", lambda db: None)
        db = MagicMock()
        alerts = generate_bond_spread_alerts(db)
        assert alerts == []

    def test_alert_for_high_spread(self, monkeypatch):
        monkeypatch.setattr("src.collectors.macro.get_latest_key_rate", lambda db: 7.5)
        db = MagicMock()
        mock_offering = MagicMock()
        mock_offering.yield_to_maturity = 18.0
        mock_offering.credit_rating = "BB"
        mock_offering.maturity_date = date.today() + timedelta(days=365)
        mock_ticker = "HIGHSPREAD"
        db.query().join().filter().all.return_value = [(mock_offering, mock_ticker)]

        alerts = generate_bond_spread_alerts(db, spread_threshold=5.0)
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "bond_spread"
        assert "спред" in alerts[0]["title"].lower()
