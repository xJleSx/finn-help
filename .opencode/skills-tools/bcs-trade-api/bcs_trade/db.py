"""SQLite schema and migrations.

Two tables only — see AGENTS.md §3 (SQLite как «лёгкая история»).
Migration version is tracked in `schema_version`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_FILE

CURRENT_VERSION = 1

DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          INTEGER NOT NULL,
        label       TEXT,
        account     TEXT,
        payload     TEXT NOT NULL,
        total_rub   REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON portfolio_snapshots(ts)",
    """
    CREATE TABLE IF NOT EXISTS last_quotes (
        ticker      TEXT PRIMARY KEY,
        ts          INTEGER NOT NULL,
        bid         REAL,
        ask         REAL,
        last        REAL,
        payload     TEXT
    )
    """,
]


def _connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (CURRENT_VERSION,))
            for stmt in DDL:
                conn.execute(stmt)
        elif row["version"] < CURRENT_VERSION:
            # Migrations would go here. For v0.1 the only version is 1.
            conn.execute(
                "UPDATE schema_version SET version = ?", (CURRENT_VERSION,)
            )
        conn.commit()


def get_conn() -> sqlite3.Connection:
    """Public accessor used by `cache.py`. Ensures schema is up to date."""
    init_db()
    return _connect()
