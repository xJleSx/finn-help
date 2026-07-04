"""Smoke tests for the CLI — no network, no token required.

These tests verify wiring: --help works, unknown commands fail with
code 2, missing config produces a clear error.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "fmc.py"), *args],
        capture_output=True,
        env=env,
    )


def test_help_exits_zero() -> None:
    r = _run("--help")
    assert r.returncode == 0
    out = r.stdout.decode("utf-8", "replace")
    assert "FinanceMarker" in out


def test_version_exits_zero() -> None:
    r = _run("--version")
    assert r.returncode == 0
    out = r.stdout.decode("utf-8", "replace").strip()
    assert out.startswith("fmc ")


def test_unknown_subcommand_fails() -> None:
    r = _run("nope")
    assert r.returncode == 2


def test_missing_token_fails_with_clear_error(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["FMC_ENV_FILE"] = str(tmp_path / "no-such-env")
    env.pop("FM_API_TOKEN", None)
    r = _run("token", env=env)
    assert r.returncode == 2
    blob = (r.stdout + r.stderr).decode("utf-8", "replace")
    assert "FM_API_TOKEN" in blob


def test_stocks_unknown_flag_rejected() -> None:
    env = os.environ.copy()
    env["FMC_ENV_FILE"] = "nope"
    env["FM_API_TOKEN"] = "dummy"
    r = _run("stocks", "--bogus", env=env)
    assert r.returncode == 2
