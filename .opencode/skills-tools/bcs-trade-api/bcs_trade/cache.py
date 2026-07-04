"""High-level cache helpers: snapshot save/list, last-quote upsert.

The cache is a *stateful landing pad*, not a response cache. Every
command still hits BCS live; this module only persists what we saw.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .config import Config
from .db import get_conn
from .errors import BcsError
from .http_client import request_json
from .auth import auth_header
from .portfolio import dedupe_positions, filter_by_term, get_portfolio


def save_portfolio_snapshot(
    cfg: Config,
    label: str | None = None,
    term: str = "T0",
) -> dict[str, Any]:
    """Snapshot the current portfolio.

    `term` selects the settlement horizon. Default `T0` = the live,
    tradable position. `T1`/`T2`/`T365` show planned settlements of
    the same holdings — useful for futures planning, never the source
    of truth for "what do I own right now".
    """
    raw = get_portfolio(cfg)
    # Always persist the FULL raw payload (audit trail) but compute the
    # accounting total on the de-duplicated, T0-only view.
    current = dedupe_positions(filter_by_term(raw, term=term))
    total = _extract_total(current)
    ts = int(time.time())
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO portfolio_snapshots(ts, label, account, payload, total_rub) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, label, cfg.account, json.dumps(raw, ensure_ascii=False), total),
        )
        conn.commit()
        snap_id = cur.lastrowid
    return {"id": snap_id, "ts": ts, "label": label, "term": term, "total_rub": total}


def list_snapshots(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, label, account, total_rub "
            "FROM portfolio_snapshots ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def remember_quote(ticker: str, quote: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO last_quotes(ticker, ts, bid, ask, last, payload) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            "ts=excluded.ts, bid=excluded.bid, ask=excluded.ask, last=excluded.last, "
            "payload=excluded.payload",
            (
                ticker,
                int(time.time()),
                quote.get("bid"),
                quote.get("ask"),
                quote.get("last"),
                json.dumps(quote, ensure_ascii=False),
            ),
        )
        conn.commit()


def get_last_quote(ticker: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM last_quotes WHERE ticker = ?", (ticker,)
        ).fetchone()
    return dict(row) if row else None


def _extract_total(payload: Any) -> float | None:
    """Sum `currentValueRub` across records.

    BCS `/portfolio` returns a list of `moneyLimit` and `depoLimit`
    records. Each carries its own `currentValueRub`; the natural total
    is the sum of those fields. Falls back to dict shape for safety.
    """
    if isinstance(payload, list):
        total = 0.0
        seen = False
        for item in payload:
            if not isinstance(item, dict):
                continue
            v = item.get("currentValueRub")
            if isinstance(v, (int, float)):
                total += float(v)
                seen = True
        return total if seen else None
    if isinstance(payload, dict):
        for key in ("total", "totalCost", "evaluation", "cost"):
            v = payload.get(key)
            if isinstance(v, (int, float)):
                return float(v)
    return None


# ---------- CLI dispatch ----------


def run(subcommand: str, cfg: Config, term: str = "T0") -> dict[str, Any]:
    if subcommand == "save":
        return save_portfolio_snapshot(cfg, term=term)
    if subcommand == "list":
        return {"snapshots": list_snapshots()}
    raise BcsError(f"unknown snapshot subcommand: {subcommand}")


# Re-export so `bcs snapshot save` can hit BCS without importing
# portfolio + auth + http_client separately in bcs.py.
__all__ = [
    "run",
    "save_portfolio_snapshot",
    "list_snapshots",
    "remember_quote",
    "get_last_quote",
    "_extract_total",
]
