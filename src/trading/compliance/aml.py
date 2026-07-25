from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from src.db.connection import get_session
from src.db.models.risk import AMLState
from src.trading.types import AMLRecord, ComplianceCheck

logger = logging.getLogger(__name__)

SUSPICIOUS_COUNTRY_RISK: dict[str, float] = {}
HIGH_RISK_THRESHOLD_RUB: float = 1_000_000
STRUCTURING_THRESHOLD_RUB: float = 600_000
STRUCTURING_WINDOW_HOURS: int = 24
MAX_DAILY_VOLUME_RUB: float = 10_000_000
PEP_THRESHOLD_RUB: float = 5_000_000

_user_daily_volume: dict[int, float] = {}
_user_daily_volume_date: dict[int, date] = {}
_user_tx_timestamps: dict[int, list[dict[str, Any]]] = {}
_user_velocity: dict[int, list[float]] = {}


def _load_user_state(user_id: int) -> None:
    if user_id in _user_daily_volume:
        return
    try:
        db = get_session()
        try:
            row = db.query(AMLState).filter(AMLState.user_id == user_id).first()
            if row is not None:
                _user_daily_volume[user_id] = row.daily_volume or 0.0
                _user_daily_volume_date[user_id] = row.date
                _user_tx_timestamps[user_id] = list(row.tx_timestamps_json or [])
                _user_velocity[user_id] = list(row.velocity_timestamps_json or [])
        finally:
            db.close()
    except Exception as e:
        logger.debug("Could not load AML state for user %d from DB: %s", user_id, e)
        _user_daily_volume.setdefault(user_id, 0.0)
        _user_daily_volume_date.setdefault(user_id, date.today())
        _user_tx_timestamps.setdefault(user_id, [])
        _user_velocity.setdefault(user_id, [])


def _save_user_state(user_id: int) -> None:
    try:
        db = get_session()
        try:
            row = db.query(AMLState).filter(AMLState.user_id == user_id).first()
            if row is None:
                row = AMLState(user_id=user_id)
                db.add(row)
            row.date = _user_daily_volume_date.get(user_id, date.today())
            row.daily_volume = _user_daily_volume.get(user_id, 0.0)
            row.tx_timestamps_json = _user_tx_timestamps.get(user_id, [])
            row.velocity_timestamps_json = _user_velocity.get(user_id, [])
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception as e:
        logger.debug("Could not persist AML state for user %d: %s", user_id, e)


def _reset_daily_if_needed(user_id: int) -> None:
    _load_user_state(user_id)
    _user_daily_volume.setdefault(user_id, 0.0)
    _user_daily_volume_date.setdefault(user_id, date.today())
    _user_tx_timestamps.setdefault(user_id, [])
    today = date.today()
    if _user_daily_volume_date[user_id] != today:
        _user_daily_volume[user_id] = 0.0
        _user_daily_volume_date[user_id] = today


def _check_volume_threshold(ticker: str, volume_rub: float, user_id: int) -> list[str]:
    warnings: list[str] = []
    if volume_rub >= HIGH_RISK_THRESHOLD_RUB:
        warnings.append(f"High volume {volume_rub:,.0f} RUB for {ticker}")
    _reset_daily_if_needed(user_id)
    _user_daily_volume[user_id] += volume_rub
    if _user_daily_volume[user_id] > MAX_DAILY_VOLUME_RUB:
        warnings.append(f"Daily volume limit exceeded: {_user_daily_volume[user_id]:,.0f} RUB")
    _save_user_state(user_id)
    return warnings


def _check_round_trip(ticker: str, user_id: int, volume_rub: float) -> list[str]:
    warnings: list[str] = []
    _reset_daily_if_needed(user_id)
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - STRUCTURING_WINDOW_HOURS * 3600
    _user_tx_timestamps[user_id] = [t for t in _user_tx_timestamps[user_id] if t["timestamp"] > cutoff]
    _user_tx_timestamps[user_id].append({"ticker": ticker, "volume": volume_rub, "timestamp": now})
    recent_volume = sum(t["volume"] for t in _user_tx_timestamps[user_id] if t["ticker"] == ticker)
    if STRUCTURING_THRESHOLD_RUB * 0.9 <= volume_rub <= STRUCTURING_THRESHOLD_RUB * 1.1:
        warnings.append(f"Structuring pattern detected: {volume_rub:,.0f} RUB near threshold")
    if recent_volume > STRUCTURING_THRESHOLD_RUB * 3:
        warnings.append(f"Round-trip structuring: {recent_volume:,.0f} RUB in {STRUCTURING_WINDOW_HOURS}h")
    _save_user_state(user_id)
    return warnings


def _check_velocity(user_id: int) -> list[str]:
    warnings: list[str] = []
    _reset_daily_if_needed(user_id)
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 3600
    _user_velocity.setdefault(user_id, [])
    _user_velocity[user_id] = [t for t in _user_velocity[user_id] if t > cutoff]
    _user_velocity[user_id].append(now)
    if len(_user_velocity[user_id]) > 20:
        warnings.append(f"High tx velocity: {len(_user_velocity[user_id])} tx/hour")
    _save_user_state(user_id)
    return warnings


def check_order_aml(
    user_id: int,
    ticker: str,
    volume_rub: float,
    user_risk_profile: str = "balanced",
) -> ComplianceCheck:
    check = ComplianceCheck()
    try:
        check.checks.append({"check": "volume_threshold", "volume_rub": volume_rub})
        volume_warnings = _check_volume_threshold(ticker, volume_rub, user_id)
        check.warnings.extend(volume_warnings)
    except Exception as e:
        logger.error("AML volume check error (db): %s", e)
        check.warnings.append(f"AML volume check db error: {e}")

    try:
        check.checks.append({"check": "structuring", "volume_rub": volume_rub})
        structuring_warnings = _check_round_trip(ticker, user_id, volume_rub)
        check.warnings.extend(structuring_warnings)
    except Exception as e:
        logger.error("AML structuring check error (db): %s", e)
        check.warnings.append(f"AML structuring check db error: {e}")

    try:
        check.checks.append({"check": "velocity"})
        velocity_warnings = _check_velocity(user_id)
        check.warnings.extend(velocity_warnings)
    except Exception as e:
        logger.error("AML velocity check error (db): %s", e)
        check.warnings.append(f"AML velocity check db error: {e}")

    try:
        if user_risk_profile == "insane" and volume_rub > HIGH_RISK_THRESHOLD_RUB * 5:
            check.blocks.append(f"Insane profile blocked for volume {volume_rub:,.0f} RUB")
            check.passed = False

        if volume_rub > PEP_THRESHOLD_RUB:
            check.warnings.append(f"PEP-level volume: {volume_rub:,.0f} RUB")

        if check.blocks:
            check.passed = False
            logger.warning(
                "AML BLOCKED user=%d ticker=%s volume=%.2f reasons=%s",
                user_id,
                ticker,
                volume_rub,
                check.blocks,
            )
    except Exception as e:
        logger.error("AML check error (system): %s", e, exc_info=True)
        check.warnings.append(f"AML system error: {e}")
    return check


def create_aml_record(
    user_id: int,
    ticker: str,
    volume_rub: float,
    pattern: str,
    risk_score: float,
    flagged: bool,
    reason: str = "",
) -> AMLRecord:
    return AMLRecord(
        user_id=user_id,
        ticker=ticker,
        volume_rub=volume_rub,
        pattern=pattern,
        risk_score=risk_score,
        flagged=flagged,
        reason=reason,
    )


def reset_aml_state() -> None:
    _user_daily_volume.clear()
    _user_tx_timestamps.clear()
    _user_velocity.clear()
    try:
        db = get_session()
        try:
            db.query(AMLState).delete()
            db.commit()
            logger.info("AML state reset — all rows cleared from DB")
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception as e:
        logger.debug("Could not clear AML state from DB: %s", e)
