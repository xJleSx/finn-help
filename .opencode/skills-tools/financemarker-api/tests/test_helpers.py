"""Tests for pure helpers — no network, no token required."""
from __future__ import annotations

from pathlib import Path

import pytest

from financemarker import cache
from financemarker.db import init_db


@pytest.fixture()
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import financemarker.config as cfg_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cfg_mod, "CACHE_DIR", tmp_path / ".fmc-cache")
    monkeypatch.setattr(cfg_mod, "DB_FILE", tmp_path / ".fmc-cache" / "fmc.db")
    monkeypatch.setattr(cfg_mod, "TOKEN_STATUS_FILE", tmp_path / ".fmc-cache" / "token_status.json")


def test_init_db_creates_tables(isolated_cache: None) -> None:
    init_db()
    from financemarker.db import get_conn

    with get_conn() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "company_overview" in tables
    assert "dividends_recent" in tables
    assert "tickers_meta" in tables
    assert "schema_version" in tables


def test_remember_and_resolve_overview(isolated_cache: None) -> None:
    from financemarker.config import load_config

    cfg = load_config.__wrapped__() if hasattr(load_config, "__wrapped__") else None  # type: ignore[attr-defined]
    # load_config would require a token; bypass by patching _ensure_cache.
    from financemarker import config as cfg_mod

    # Direct DB calls — we don't actually need cfg for remember_overview,
    # but the signature requires it. Use a stub.
    class _StubCfg:
        pass

    info = {
        "code": "SBER",
        "exchange": "MOEX",
        "name": "Сбербанк",
        "sector": "Финансы",
        "industry": "Банки",
        "currency": "RUB",
    }
    cache.remember_overview(_StubCfg(), "MOEX", "SBER", info)

    overview = cache.get_overview("MOEX", "SBER")
    assert overview is not None
    assert overview["name"] == "Сбербанк"
    assert overview["sector"] == "Финансы"


def test_remember_and_resolve_name(isolated_cache: None) -> None:
    class _StubCfg:
        pass

    cache.remember_tickers_meta(
        _StubCfg(),
        [
            {"exchange": "MOEX", "code": "LKOH", "name": "ЛУКОЙЛ"},
            {"exchange": "MOEX", "code": "GAZP", "name": "Газпром"},
        ],
    )
    assert cache.resolve_name("MOEX", "LKOH") == "ЛУКОЙЛ"
    assert cache.resolve_name("MOEX", "GAZP") == "Газпром"
    assert cache.resolve_name("MOEX", "ZZZZ") is None


def test_parse_stock_ref_validates() -> None:
    from financemarker.errors import InvalidRequest
    from financemarker.stocks import parse_stock_ref

    assert parse_stock_ref("MOEX:SBER") == ("MOEX", "SBER")
    assert parse_stock_ref("MOEX-SBER") == ("MOEX", "SBER")
    with pytest.raises(InvalidRequest):
        parse_stock_ref("SBER")  # no exchange
    with pytest.raises(InvalidRequest):
        parse_stock_ref(":SBER")
    with pytest.raises(InvalidRequest):
        parse_stock_ref("MOEX:")
