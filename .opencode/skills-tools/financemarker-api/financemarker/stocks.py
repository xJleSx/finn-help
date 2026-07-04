"""Stocks: list and per-company detail.

The per-company detail endpoint accepts `?include=ratios,summary,…` and
is potentially large; we always cache the info block to `company_overview`
so the next call to a known ticker is fast(er).
"""
from __future__ import annotations

from typing import Any

from .cache import remember_overview, remember_tickers_meta
from .config import Config
from .endpoints import STOCK, STOCKS
from .http_client import get


def list_stocks(
    cfg: Config,
    *,
    limit: int = 30,
    offset: int = 0,
    sort_by: str | None = None,
    sort_order: str | None = None,
    updated_in_days: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if sort_by:
        params["sort_by"] = sort_by
    if sort_order:
        params["sort_order"] = sort_order
    if updated_in_days is not None:
        params["updated_in_days"] = updated_in_days

    items = get(cfg, STOCKS, params=params) or []
    if items:
        remember_tickers_meta(cfg, items)
    return items


def get_stock(
    cfg: Config,
    exchange: str,
    code: str,
    *,
    include: str | None = None,
) -> dict[str, Any]:
    path = STOCK.format(exchange=exchange, code=code)
    params: dict[str, Any] = {}
    if include:
        params["include"] = include
    payload = get(cfg, path, params=params)
    info = (payload or {}).get("info") or {}
    if info:
        remember_overview(cfg, exchange, code, info)
    return payload or {}


def parse_stock_ref(ref: str) -> tuple[str, str]:
    """Parse "MOEX:SBER" / "MOEX-SBER" / "SBER" into (exchange, code).

    Raises InvalidRequest if the format is unrecognised.
    """
    from .errors import InvalidRequest

    if ":" in ref:
        ex, code = ref.split(":", 1)
        ex, code = ex.strip().upper(), code.strip().upper()
        if not ex or not code:
            raise InvalidRequest(f"bad stock ref: {ref!r}")
        return ex, code
    if "-" in ref:
        ex, code = ref.split("-", 1)
        ex, code = ex.strip().upper(), code.strip().upper()
        if ex and code:
            return ex, code
    raise InvalidRequest(
        f"stock ref must be 'EXCHANGE:CODE' (e.g. MOEX:SBER), got {ref!r}"
    )
