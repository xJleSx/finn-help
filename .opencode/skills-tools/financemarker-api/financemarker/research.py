"""Analyst ideas, insider transactions, expert leaderboard, disclosure."""
from __future__ import annotations

from typing import Any

from .config import Config
from .endpoints import DISCLOSURE, EXPERTS, IDEA_DETAIL, IDEAS, INSIDERS
from .http_client import get


def list_ideas(
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
    return get(cfg, IDEAS, params=params) or []


def get_idea(cfg: Config, idea_id: int) -> dict[str, Any]:
    return get(cfg, IDEA_DETAIL.format(id=idea_id)) or {}


def list_insiders(
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
    return get(cfg, INSIDERS, params=params) or []


def list_experts(
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
    return get(cfg, EXPERTS, params=params) or []


def list_disclosure(
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
    return get(cfg, DISCLOSURE, params=params) or []
