"""Dividends (upcoming and past) and corporate-events calendar."""
from __future__ import annotations

from typing import Any

from .cache import remember_dividend
from .config import Config
from .endpoints import CALENDAR, DIVIDENDS
from .http_client import get


def list_dividends(
    cfg: Config,
    *,
    mode: str = "upcoming",
    limit: int = 30,
    offset: int = 0,
    sort_by: str | None = None,
    sort_order: str | None = None,
    updated_in_days: int | None = None,
) -> list[dict[str, Any]]:
    if mode not in ("upcoming", "past"):
        from .errors import InvalidRequest

        raise InvalidRequest(f"mode must be 'upcoming' or 'past', got {mode!r}")
    params: dict[str, Any] = {
        "mode": mode,
        "limit": limit,
        "offset": offset,
    }
    if sort_by:
        params["sort_by"] = sort_by
    if sort_order:
        params["sort_order"] = sort_order
    if updated_in_days is not None:
        params["updated_in_days"] = updated_in_days

    items = get(cfg, DIVIDENDS, params=params) or []
    for div in items:
        if div.get("exchange") and div.get("code"):
            remember_dividend(cfg, div["exchange"], div["code"], div)
    return items


def list_calendar(
    cfg: Config,
    *,
    limit: int = 30,
    offset: int = 0,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if sort_by:
        params["sort_by"] = sort_by
    if sort_order:
        params["sort_order"] = sort_order
    return get(cfg, CALENDAR, params=params) or []
