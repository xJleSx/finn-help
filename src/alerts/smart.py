from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_

from src.db.models import Instrument, Price, Signal, SmartAlertRule

logger = logging.getLogger(__name__)

CONDITION_FN = {
    "gt": lambda v, t: v > t,
    "lt": lambda v, t: v < t,
    "gte": lambda v, t: v >= t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: v == t,
}

SEVERITY_MAP: dict[str, int] = {"gt": 3, "gte": 3, "lt": 2, "lte": 2, "eq": 1}


class SmartAlertEngine:
    def evaluate_rules(
        self, db: Any, user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = db.query(SmartAlertRule).filter(SmartAlertRule.enabled.is_(True))
        if user_id is not None:
            query = query.filter(SmartAlertRule.user_id == user_id)
        rules = query.all()

        triggered: list[dict[str, Any]] = []
        for rule in rules:
            try:
                if self._should_trigger(db, rule):
                    triggered.append(self._build_alert(rule))
                    rule.last_triggered = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                logger.exception("smart_rule_eval_failed rule_id=%s", rule.id)
                db.rollback()
        return triggered

    def _should_trigger(self, db: Any, rule: SmartAlertRule) -> bool:
        if rule.rule_type == "price":
            return self._check_price(db, rule)
        if rule.rule_type == "signal":
            return self._check_signal(db, rule)
        if rule.rule_type == "scheduled":
            return self._check_scheduled(rule)
        return False

    def _check_price(self, db: Any, rule: SmartAlertRule) -> bool:
        instr = (
            db.query(Instrument)
            .filter(Instrument.ticker == rule.ticker)
            .first()
        )
        if instr is None:
            return False
        latest_price = (
            db.query(Price.close)
            .filter(Price.instrument_id == instr.id)
            .order_by(Price.date.desc())
            .first()
        )
        if latest_price is None or latest_price[0] is None:
            return False
        op = CONDITION_FN.get(rule.condition)
        if op is None:
            return False
        return bool(op(float(latest_price[0]), rule.threshold))

    def _check_signal(self, db: Any, rule: SmartAlertRule) -> bool:
        instr = (
            db.query(Instrument)
            .filter(Instrument.ticker == rule.ticker)
            .first()
        )
        if instr is None:
            return False
        latest = (
            db.query(Signal)
            .filter(Signal.instrument_id == instr.id)
            .order_by(Signal.created_at.desc())
            .first()
        )
        if latest is None or latest.confidence is None:
            return False
        op = CONDITION_FN.get(rule.condition)
        if op is None:
            return False
        return bool(op(float(latest.confidence), rule.threshold))

    def _check_scheduled(self, rule: SmartAlertRule) -> bool:
        if rule.last_triggered is None:
            return True
        if rule.schedule is None:
            return False
        parts = rule.schedule.split(":")
        interval = parts[0]
        now = datetime.now(timezone.utc)

        if interval == "daily":
            if len(parts) < 2:
                return False
            target_hour, target_min = map(int, parts[1].split("."))
            if now.hour != target_hour or now.minute != target_min:
                return False
            return (
                rule.last_triggered.hour != target_hour
                or rule.last_triggered.minute != target_min
                or rule.last_triggered.date() != now.date()
            )

        if interval == "weekly":
            if len(parts) < 3:
                return False
            target_day = parts[1].lower()
            target_hour, target_min = map(int, parts[2].split("."))
            if now.strftime("%A").lower() != target_day:
                return False
            if now.hour != target_hour or now.minute != target_min:
                return False
            return (
                rule.last_triggered.hour != target_hour
                or rule.last_triggered.minute != target_min
                or rule.last_triggered.isocalendar()[1] != now.isocalendar()[1]
            )

        if interval == "hourly":
            if now.hour != rule.last_triggered.hour:
                return True
            if (now - rule.last_triggered).total_seconds() >= 3600:
                return True
            return False

        return False

    def _build_alert(self, rule: SmartAlertRule) -> dict[str, Any]:
        severity = SEVERITY_MAP.get(rule.condition, 1)
        type_label = {"price": "Цена", "signal": "Сигнал", "scheduled": "Расписание"}
        cond_str = {"gt": ">", "lt": "<", "gte": "≥", "lte": "≤", "eq": "="}
        direction_word = cond_str.get(rule.condition, rule.condition)
        return {
            "ticker": rule.ticker,
            "alert_type": f"smart_{rule.rule_type}",
            "severity": float(severity),
            "title": f"⚡ Smart Alert: {rule.ticker}",
            "message": (
                f"Правило: {rule.name or rule.rule_type}\n"
                f"Тикер: {rule.ticker}\n"
                f"Условие: цена {direction_word} {rule.threshold}\n"
                f"Тип: {type_label.get(rule.rule_type, rule.rule_type)}"
            ),
            "user_id": rule.user_id,
            "rule_id": rule.id,
        }
