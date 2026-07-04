"""Portfolio and limits endpoints.

BCS quirk: `/portfolio` returns every position once per settlement term
(`T0`, `T1`, `T2`, `T365`) — these are *planned* future settlements of
the same holding, not separate lots. Naive summation 4× over-counts.

We filter to a single term (default `T0` — the live, tradable position)
and additionally dedupe by `(ticker, classCode, instrumentType)` in
case the same instrument appears under different boards.
"""
from __future__ import annotations

from typing import Any, Iterable

from .auth import auth_header
from .config import Config
from .endpoints import LIMITS_URL, PORTFOLIO_URL
from .http_client import request_json

DEFAULT_TERM = "T0"


def _url(cfg: Config, path: str) -> str:
    return f"{cfg.base_url.rstrip('/')}{path}"


def get_portfolio(
    cfg: Config,
    account: str | None = None,
    term: str = DEFAULT_TERM,
) -> dict[str, Any]:
    url = PORTFOLIO_URL
    acc = account or cfg.account
    if acc:
        url += f"?account={acc}"
    return request_json("GET", url, auth_header=auth_header(cfg))


def filter_by_term(
    raw: Iterable[dict[str, Any]] | dict[str, Any] | list[dict[str, Any]],
    term: str = DEFAULT_TERM,
) -> list[dict[str, Any]]:
    """Return only records with `term == term`.

    Accepts the list-of-records shape BCS uses, and also falls through
    unchanged for dicts (older/future shape) so callers can be loose.
    """
    if not isinstance(raw, list):
        return raw  # type: ignore[return-value]
    return [r for r in raw if isinstance(r, dict) and r.get("term") == term]


def dedupe_positions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicates that share ticker/class/instrument type.

    The BCS API can list the same instrument under different boards
    (e.g. `classCode` `TQBR` vs `SPBXM`). For portfolio accounting we
    keep the first occurrence and drop the rest. Quantity and value
    fields are kept as-is from the first record — BCS reports the
    consolidated view elsewhere via `/limits`.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for r in records:
        key = (
            str(r.get("ticker") or ""),
            str(r.get("classCode") or ""),
            str(r.get("instrumentType") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def get_limits(cfg: Config) -> dict[str, Any]:
    return request_json("GET", LIMITS_URL, auth_header=auth_header(cfg))
