from src.constants import (
    CACHE_TTL,
    COOLDOWN_SECONDS,
    KNOWN_DIVIDEND_STOCKS,
    MAX_CACHE_SIZE,
    RISK_PROFILES,
    SAFE_BONDS,
    SAFE_ETFS,
    SECTOR_LIMITS,
    SECTOR_NAMES,
)


def test_known_dividend_stocks():
    assert "SBER" in KNOWN_DIVIDEND_STOCKS
    assert KNOWN_DIVIDEND_STOCKS["SBER"] == "dividend"
    assert KNOWN_DIVIDEND_STOCKS["MOEX"] == "growth"


def test_sector_names():
    assert SECTOR_NAMES["SBER"] == "Банки"
    assert SECTOR_NAMES["GAZP"] == "Нефть и газ"


def test_safe_etfs():
    assert "FXRL" in SAFE_ETFS
    assert "TMOS" in SAFE_ETFS


def test_safe_bonds():
    assert "SU26238RMFS5" in SAFE_BONDS


def test_sector_limits():
    assert SECTOR_LIMITS["Нефть и газ"] == 0.35
    assert SECTOR_LIMITS["IT"] == 0.15


def test_risk_profiles():
    assert "conservative" in RISK_PROFILES
    assert "balanced" in RISK_PROFILES
    assert "aggressive" in RISK_PROFILES
    balanced = RISK_PROFILES["balanced"]
    assert balanced["max_position_pct"] == 20
    assert balanced["min_confidence"] == 0.3


def test_cache_constants():
    assert CACHE_TTL == 300
    assert MAX_CACHE_SIZE == 100
    assert COOLDOWN_SECONDS == 5
