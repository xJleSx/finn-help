from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.alerts.smart import SmartAlertEngine
from src.db.models import Instrument, Price, Signal, SmartAlertRule


@pytest.fixture(autouse=True)
def _clean_db(db_session):
    for table in (SmartAlertRule, Signal, Price, Instrument):
        db_session.query(table).delete()
    db_session.commit()


def _make_instrument(db, ticker: str) -> Instrument:
    instr = Instrument(ticker=ticker, full_name=ticker, instrument_type="stock", exchange="MOEX")
    db.add(instr)
    db.flush()
    return instr


def _add_price(db, instr_id: int, close: float):
    price = Price(instrument_id=instr_id, close=close, date=datetime.now(timezone.utc).date())
    db.add(price)
    db.flush()


def _add_signal(db, instr_id: int, confidence: float):
    sig = Signal(instrument_id=instr_id, action="buy", confidence=confidence)
    db.add(sig)
    db.flush()


class TestSmartAlertEngine:
    def test_no_rules_returns_empty(self, db_session):
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert result == []

    def test_disabled_rules_skipped(self, db_session):
        rule = SmartAlertRule(
            user_id=1, rule_type="price", ticker="SBER",
            condition="gt", threshold=100, enabled=False,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert result == []

    def test_price_rule_gt_triggers(self, db_session):
        instr = _make_instrument(db_session, "SBER")
        _add_price(db_session, instr.id, 300)
        rule = SmartAlertRule(
            user_id=1, name="SBER high", rule_type="price", ticker="SBER",
            condition="gt", threshold=250, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert len(result) == 1
        assert result[0]["ticker"] == "SBER"
        assert result[0]["alert_type"] == "smart_price"

    def test_price_rule_gt_not_triggered(self, db_session):
        instr = _make_instrument(db_session, "SBER")
        _add_price(db_session, instr.id, 200)
        rule = SmartAlertRule(
            user_id=1, rule_type="price", ticker="SBER",
            condition="gt", threshold=250, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert result == []

    def test_price_rule_lt_triggers(self, db_session):
        instr = _make_instrument(db_session, "GAZP")
        _add_price(db_session, instr.id, 150)
        rule = SmartAlertRule(
            user_id=1, rule_type="price", ticker="GAZP",
            condition="lt", threshold=200, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert len(result) == 1

    def test_signal_rule_triggers(self, db_session):
        instr = _make_instrument(db_session, "SBER")
        _add_signal(db_session, instr.id, 0.8)
        rule = SmartAlertRule(
            user_id=1, rule_type="signal", ticker="SBER",
            condition="gt", threshold=0.7, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert len(result) == 1

    def test_signal_rule_not_triggered(self, db_session):
        instr = _make_instrument(db_session, "SBER")
        _add_signal(db_session, instr.id, 0.5)
        rule = SmartAlertRule(
            user_id=1, rule_type="signal", ticker="SBER",
            condition="gt", threshold=0.7, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert result == []

    def test_scheduled_rule_triggers_first_time(self, db_session):
        rule = SmartAlertRule(
            user_id=1, rule_type="scheduled", ticker="ALL",
            condition="eq", threshold=0, schedule="daily:0.0",
            last_triggered=None, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert len(result) == 1

    def test_scheduled_rule_does_not_trigger_again_same_minute(self, db_session):
        now = datetime.now(timezone.utc)
        same_minute = now.replace(minute=now.minute)
        rule = SmartAlertRule(
            user_id=1, rule_type="scheduled", ticker="ALL",
            condition="eq", threshold=0, schedule=f"daily:{now.hour}.{now.minute}",
            last_triggered=same_minute,
            enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert result == []

    def test_evaluate_rules_by_user_id(self, db_session):
        instr = _make_instrument(db_session, "SBER")
        _add_price(db_session, instr.id, 300)
        rule = SmartAlertRule(
            user_id=1, rule_type="price", ticker="SBER",
            condition="gt", threshold=250, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session, user_id=2)
        assert result == []

    def test_no_price_data_does_not_trigger(self, db_session):
        _make_instrument(db_session, "SBER")
        rule = SmartAlertRule(
            user_id=1, rule_type="price", ticker="SBER",
            condition="gt", threshold=250, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert result == []

    def test_last_triggered_updated_after_evaluation(self, db_session):
        instr = _make_instrument(db_session, "SBER")
        _add_price(db_session, instr.id, 300)
        rule = SmartAlertRule(
            user_id=1, rule_type="price", ticker="SBER",
            condition="gt", threshold=250, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        engine.evaluate_rules(db_session)
        db_session.refresh(rule)
        assert rule.last_triggered is not None

    def test_invalid_condition_returns_empty(self, db_session):
        instr = _make_instrument(db_session, "SBER")
        _add_price(db_session, instr.id, 300)
        rule = SmartAlertRule(
            user_id=1, rule_type="price", ticker="SBER",
            condition="invalid", threshold=250, enabled=True,
        )
        db_session.add(rule)
        db_session.commit()
        engine = SmartAlertEngine()
        result = engine.evaluate_rules(db_session)
        assert result == []
