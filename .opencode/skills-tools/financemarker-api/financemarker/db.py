"""SQLite schema and migrations.

Tables are intentionally narrow — only the bits we want to persist for
the cross-session "what did we see last" use case. Full payloads go in
`payload` JSON if we need to re-derive later.
"""
from __future__ import annotations

import sqlite3

from .config import DB_FILE

CURRENT_VERSION = 1

DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS company_overview (
        exchange     TEXT NOT NULL,
        code         TEXT NOT NULL,
        ts           INTEGER NOT NULL,
        name         TEXT,
        sector       TEXT,
        industry     TEXT,
        currency     TEXT,
        payload      TEXT NOT NULL,
        PRIMARY KEY (exchange, code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dividends_recent (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        exchange      TEXT NOT NULL,
        code          TEXT NOT NULL,
        year          INTEGER,
        div_amount    REAL,
        div_curr      TEXT,
        div_percent   REAL,
        last_buy_date TEXT,
        reestr_close  TEXT,
        ts            INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_div_code ON dividends_recent(exchange, code, year)",
    """
    CREATE TABLE IF NOT EXISTS tickers_meta (
        exchange TEXT NOT NULL,
        code     TEXT NOT NULL,
        name     TEXT,
        ts       INTEGER NOT NULL,
        PRIMARY KEY (exchange, code)
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
            conn.execute(
                "INSERT INTO schema_version(version) VALUES (?)", (CURRENT_VERSION,)
            )
            for stmt in DDL:
                conn.execute(stmt)
        elif row["version"] < CURRENT_VERSION:
            conn.execute(
                "UPDATE schema_version SET version = ?", (CURRENT_VERSION,)
            )
        conn.commit()


def get_conn() -> sqlite3.Connection:
    init_db()
    return _connect()
