"""Stateful cache helpers — separate from response caching.

The agent still hits the API live on every call; we only persist
*what we saw* so cross-session lookups (e.g. "did I check this ticker
recently?") are cheap.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .config import Config
from .db import get_conn


def remember_overview(
    cfg: Config, exchange: str, code: str, info: dict[str, Any]
) -> None:
    ts = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO company_overview(exchange, code, ts, name, sector, industry, currency, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, code) DO UPDATE SET
                ts=excluded.ts,
                name=excluded.name,
                sector=excluded.sector,
                industry=excluded.industry,
                currency=excluded.currency,
                payload=excluded.payload
            """,
            (
                exchange,
                code,
                ts,
                info.get("name"),
                info.get("sector"),
                info.get("industry"),
                info.get("currency"),
                json.dumps(info, ensure_ascii=False),
            ),
        )
        conn.commit()


def get_overview(exchange: str, code: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM company_overview WHERE exchange = ? AND code = ?",
            (exchange, code),
        ).fetchone()
    return dict(row) if row else None


def remember_dividend(
    cfg: Config,
    exchange: str,
    code: str,
    div: dict[str, Any],
) -> None:
    ts = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO dividends_recent(
                exchange, code, year, div_amount, div_curr, div_percent,
                last_buy_date, reestr_close, ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exchange,
                code,
                div.get("year"),
                div.get("div_amount"),
                div.get("div_curr"),
                div.get("div_percent"),
                div.get("last_buy_date"),
                div.get("reestr_close_date"),
                ts,
            ),
        )
        conn.commit()


def remember_tickers_meta(
    cfg: Config, items: list[dict[str, Any]]
) -> None:
    ts = int(time.time())
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO tickers_meta(exchange, code, name, ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(exchange, code) DO UPDATE SET
                name=excluded.name, ts=excluded.ts
            """,
            [
                (it.get("exchange"), it.get("code"), it.get("name"), ts)
                for it in items
                if it.get("exchange") and it.get("code")
            ],
        )
        conn.commit()


def resolve_name(exchange: str, code: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM tickers_meta WHERE exchange = ? AND code = ?",
            (exchange, code),
        ).fetchone()
    return row["name"] if row else None


__all__ = [
    "remember_overview",
    "get_overview",
    "remember_dividend",
    "remember_tickers_meta",
    "resolve_name",
]
