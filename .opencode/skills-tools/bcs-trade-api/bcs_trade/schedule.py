"""Trading schedule and market status."""
from __future__ import annotations

from typing import Any

from .auth import auth_header
from .config import Config
from .endpoints import TRADING_SCHEDULE_URL, TRADING_STATUS_URL
from .errors import BcsError
from .http_client import request_json


def get_daily_schedule(cfg: Config, ticker: str = "SBER", class_code: str = "TQBR") -> dict[str, Any]:
    url = f"{TRADING_SCHEDULE_URL}?classCode={class_code}&ticker={ticker}"
    return request_json("GET", url, auth_header=auth_header(cfg))


def get_trading_status(cfg: Config, class_code: str = "TQBR") -> dict[str, Any]:
    url = f"{TRADING_STATUS_URL}?classCode={class_code}"
    return request_json("GET", url, auth_header=auth_header(cfg))


def run(subcommand: str, args: dict, cfg: Config) -> dict[str, Any]:
    if subcommand == "today":
        return get_daily_schedule(cfg, args.get("ticker", "SBER"), args.get("class_code", "TQBR"))
    if subcommand == "status":
        return get_trading_status(cfg, args.get("class_code", "TQBR"))
    raise BcsError(f"unknown schedule subcommand: {subcommand}")
