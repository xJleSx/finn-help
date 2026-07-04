"""Smoke tests for the CLI — no network, no token required.

These tests just verify that the CLI is wired up correctly: --help
works, unknown commands fail with code 2, and config validation
rejects a missing refresh token with a clear error.
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
        [sys.executable, str(ROOT / "bcs.py"), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_help_exits_zero() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "BCS Trade API CLI" in r.stdout


def test_version_exits_zero() -> None:
    r = _run("--version")
    assert r.returncode == 0
    assert r.stdout.strip().startswith("bcs ")


def test_unknown_subcommand_fails() -> None:
    r = _run("nope")
    assert r.returncode == 2


def test_missing_token_fails_with_clear_error(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["BCS_ENV_FILE"] = str(tmp_path / "no-such-env")
    env.pop("BCS_REFRESH_TOKEN", None)
    r = _run("auth", "status", env=env)
    assert r.returncode == 2
    assert "BCS_REFRESH_TOKEN" in r.stderr or "BCS_REFRESH_TOKEN" in r.stdout
