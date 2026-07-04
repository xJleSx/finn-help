"""Trades / fills endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .auth import auth_header
from .config import Config
from .endpoints import TRADES_BFF, TRADES_SEARCH_URL
from .errors import BcsError, NotConfigured
from .http_client import request_json


def list_trades(
    cfg: Config,
    *,
    days: int = 7,
    ticker: str | None = None,
) -> dict[str, Any]:
    if not TRADES_BFF:
        raise NotConfigured(
            "trades BFF prefix unknown; update bcs_trade/endpoints.py"
        )
    now = datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "startDateTime": (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z"),
        "endDateTime": now.strftime("%Y-%m-%dT23:59:59.000Z"),
    }
    if ticker:
        body["tickers"] = [ticker]
    return request_json(
        "POST",
        TRADES_SEARCH_URL,
        json_body=body,
        auth_header=auth_header(cfg),
    )


def run(subcommand: str, args: dict, cfg: Config) -> dict[str, Any]:
    if subcommand == "list":
        return list_trades(
            cfg,
            days=args.get("days", 7),
            ticker=args.get("ticker"),
        )
    raise BcsError(f"unknown trades subcommand: {subcommand}")
