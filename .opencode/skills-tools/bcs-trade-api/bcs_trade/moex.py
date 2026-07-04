"""MOEX ISS API — free market data with 15-min delay.

ISS (Informational & Statistical Server) provides access to MOEX market
data. Free tier: delayed 15 min. No auth required.

Key endpoints:
- /iss/securities/{ticker}.json — security reference
- /iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json — market data
- /iss/statistics/engines/stock/splits.json — all splits
- /iss/engines/stock/markets/shares/securities/{ticker}/candles.json — OHLCV
"""
from __future__ import annotations

import logging
from typing import Any

from .http_client import request_json

log = logging.getLogger("bcs_trade.moex")

ISS_BASE = "https://iss.moex.com/iss"


def _get(path: str, **params: Any) -> dict[str, Any]:
    """GET from ISS with iss.meta=off by default."""
    params.setdefault("iss.meta", "off")
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{ISS_BASE}{path}?{query}"
    return request_json("GET", url)


def get_security(ticker: str) -> dict[str, Any]:
    """Security reference: ISIN, lot size, face value, etc."""
    return _get(f"/securities/{ticker}.json")


def get_market_data(ticker: str, board: str = "TQBR") -> dict[str, Any]:
    """Real-time market data (delayed 15 min) for a security on a board."""
    return _get(f"/engines/stock/markets/shares/boards/{board}/securities/{ticker}.json")


def get_splits(ticker: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Historical splits. Filter by ticker if provided."""
    data = _get("/statistics/engines/stock/splits.json", limit=str(limit))
    if ticker and "splits" in data:
        rows = data["splits"].get("data", [])
        cols = data["splits"].get("columns", [])
        if rows and cols:
            secid_idx = cols.index("secid") if "secid" in cols else -1
            filtered = [r for r in rows if secid_idx >= 0 and r[secid_idx] == ticker]
            data["splits"]["data"] = filtered
    return data


def get_candles(
    ticker: str,
    *,
    from_date: str | None = None,
    till_date: str | None = None,
    interval: int = 24,
    limit: int = 100,
) -> dict[str, Any]:
    """Historical OHLCV candles.

    interval: 1=1min, 5=5min, 10=10min, 15=15min, 30=30min, 60=1h, 24=1d
    """
    params: dict[str, Any] = {"interval": str(interval), "limit": str(limit)}
    if from_date:
        params["from"] = from_date
    if till_date:
        params["till"] = till_date
    return _get(f"/engines/stock/markets/shares/securities/{ticker}/candles.json", **params)


def run(subcommand: str, args: dict) -> dict[str, Any]:
    """CLI dispatch (no BCS config needed — ISS is free, no auth)."""
    if subcommand == "security":
        return get_security(args["ticker"])
    if subcommand == "splits":
        return get_splits(args.get("ticker"), args.get("limit", 100))
    if subcommand == "candles":
        return get_candles(
            args["ticker"],
            from_date=args.get("from"),
            till_date=args.get("till"),
            interval=args.get("interval", 24),
            limit=args.get("limit", 100),
        )
    if subcommand == "quote":
        return get_market_data(args["ticker"], args.get("board", "TQBR"))
    raise ValueError(f"unknown moex subcommand: {subcommand}")
