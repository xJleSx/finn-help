"""Live tests against the real FinanceMarker API.

Marked with `pytest.mark.live`. Run explicitly:

    FM_API_TOKEN=… pytest -q -m live

These are intentionally NOT in the default test run.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.live


def _has_token() -> bool:
    return bool(os.environ.get("FM_API_TOKEN"))


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "fmc.py"), *args],
        capture_output=True,
    )


@pytest.mark.skipif(not _has_token(), reason="FM_API_TOKEN not set")
def test_token_info_ok() -> None:
    r = _run("token")
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    out = r.stdout.decode("utf-8")
    assert "day_limit" in out
    assert "valid_to" in out


@pytest.mark.skipif(not _has_token(), reason="FM_API_TOKEN not set")
def test_stock_moex_lkoh_returns_info() -> None:
    r = _run("stock", "MOEX:LKOH", "--include", "summary,ratios")
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    import json

    payload = json.loads(r.stdout)
    info = payload.get("info") or {}
    assert info.get("code") == "LKOH"
    assert info.get("exchange") == "MOEX"
    assert (payload.get("summary") or {}).get("pe") is not None
