"""SQLite migration and CRUD tests — no network."""
from __future__ import annotations

from pathlib import Path

import pytest

from bcs_trade import cache, db


@pytest.fixture()
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Force a clean DB by pointing the config at the tmp dir.
    import bcs_trade.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "CACHE_DIR", tmp_path / ".bcs-cache")
    monkeypatch.setattr(cfg_mod, "DB_FILE", tmp_path / ".bcs-cache" / "bcs.db")
    monkeypatch.setattr(cfg_mod, "TOKENS_FILE", tmp_path / ".bcs-cache" / "tokens.json")


def test_init_db_creates_tables(isolated_cache: None) -> None:
    db.init_db()
    with db.get_conn() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "portfolio_snapshots" in tables
    assert "last_quotes" in tables
    assert "schema_version" in tables


def test_remember_and_get_quote(isolated_cache: None) -> None:
    cache.remember_quote("SBER", {"bid": 100.0, "ask": 101.0, "last": 100.5})
    q = cache.get_last_quote("SBER")
    assert q is not None
    assert q["ticker"] == "SBER"
    assert q["last"] == 100.5


def test_quote_upsert_overwrites(isolated_cache: None) -> None:
    cache.remember_quote("SBER", {"last": 100.0})
    cache.remember_quote("SBER", {"last": 110.0})
    q = cache.get_last_quote("SBER")
    assert q is not None
    assert q["last"] == 110.0
