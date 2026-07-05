"""Tests for AML compliance checks"""

from __future__ import annotations

from src.trading.compliance.aml import (
    check_order_aml,
    create_aml_record,
    reset_aml_state,
)


def setup_function():
    reset_aml_state()


def test_aml_check_low_volume():
    result = check_order_aml(user_id=1, ticker="SBER", volume_rub=100_000)
    assert result.passed is True
    assert len(result.blocks) == 0


def test_aml_check_high_volume():
    result = check_order_aml(user_id=1, ticker="SBER", volume_rub=5_000_000)
    assert len(result.warnings) > 0
    has_high_volume = any("High volume" in w for w in result.warnings)
    assert has_high_volume is True


def test_aml_check_very_high_volume():
    result = check_order_aml(user_id=1, ticker="SBER", volume_rub=50_000_000)
    assert len(result.warnings) > 0


def test_aml_check_structuring():
    for _ in range(3):
        result = check_order_aml(user_id=2, ticker="GAZP", volume_rub=550_000)
    has_structuring = any("Structuring" in w for w in result.warnings)
    assert has_structuring is True


def test_aml_check_velocity():
    for _ in range(25):
        result = check_order_aml(user_id=3, ticker="VTBR", volume_rub=10_000)
    has_velocity = any("velocity" in w.lower() for w in result.warnings)
    assert has_velocity is True


def test_aml_check_insane_profile_blocked():
    result = check_order_aml(user_id=4, ticker="SBER", volume_rub=10_000_000, user_risk_profile="insane")
    assert result.passed is False
    assert len(result.blocks) > 0


def test_aml_check_pep_volume():
    result = check_order_aml(user_id=5, ticker="LKOH", volume_rub=6_000_000)
    has_pep = any("PEP" in w for w in result.warnings)
    assert has_pep is True


def test_create_aml_record():
    record = create_aml_record(
        user_id=1,
        ticker="SBER",
        volume_rub=1_000_000,
        pattern="high_volume",
        risk_score=0.7,
        flagged=True,
        reason="Test flag",
    )
    assert record.user_id == 1
    assert record.ticker == "SBER"
    assert record.pattern == "high_volume"
    assert record.flagged is True


def test_reset_aml_state():
    check_order_aml(user_id=1, ticker="SBER", volume_rub=5_000_000)
    reset_aml_state()
    result = check_order_aml(user_id=1, ticker="SBER", volume_rub=100_000)
    assert result.passed is True
    assert len(result.warnings) == 0
