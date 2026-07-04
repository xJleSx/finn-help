"""Market data and instrument reference."""
from __future__ import annotations

from typing import Any

from .auth import auth_header
from .cache import remember_quote
from .config import Config
from .endpoints import (
    CANDLES_URL,
    INSTRUMENTS_BY_TICKERS_URL,
    INSTRUMENTS_BY_TYPE_URL,
    ORDER_BOOK_URL,
    QUOTES_URL,
)
from .errors import BcsError
from .http_client import request_json


def get_quote(cfg: Config, ticker: str, class_code: str = "TQBR") -> dict[str, Any]:
    url = QUOTES_URL
    body = {"instruments": [{"ticker": ticker, "classCode": class_code}]}
    raw = request_json("POST", url, json_body=body, auth_header=auth_header(cfg))
    quote = raw if isinstance(raw, dict) else {"raw": raw}
    remember_quote(ticker, quote)
    return quote


def search_instrument(cfg: Config, query: str) -> dict[str, Any]:
    url = INSTRUMENTS_BY_TICKERS_URL
    return request_json(
        "POST", url, json_body={"tickers": [query]}, auth_header=auth_header(cfg)
    )


def get_instruments_by_isins(cfg: Config, isins: list[str]) -> dict[str, Any]:
    url = INSTRUMENTS_BY_ISINS_URL
    return request_json(
        "POST", url, json_body={"isins": isins}, auth_header=auth_header(cfg)
    )


def get_instruments_by_type(cfg: Config, type_: str, page: int = 0, size: int = 50) -> dict[str, Any]:
    url = f"{INSTRUMENTS_BY_TYPE_URL}?type={type_}&page={page}&size={size}"
    return request_json("GET", url, auth_header=auth_header(cfg))


def get_candles(cfg: Config, ticker: str, class_code: str = "TQBR") -> dict[str, Any]:
    url = CANDLES_URL
    body = {"ticker": ticker, "classCode": class_code}
    return request_json("POST", url, json_body=body, auth_header=auth_header(cfg))


def get_order_book(cfg: Config, ticker: str, class_code: str = "TQBR") -> dict[str, Any]:
    url = ORDER_BOOK_URL
    body = {"ticker": ticker, "classCode": class_code}
    return request_json("POST", url, json_body=body, auth_header=auth_header(cfg))


def run(subcommand: str, args: dict, cfg: Config) -> dict[str, Any]:
    if subcommand == "quote":
        return get_quote(cfg, args["ticker"], args.get("class_code", "TQBR"))
    if subcommand == "search":
        return search_instrument(cfg, args["query"])
    if subcommand == "by-type":
        return get_instruments_by_type(cfg, args["type"], args.get("page", 0), args.get("size", 50))
    if subcommand == "candles":
        return get_candles(cfg, args["ticker"], args.get("class_code", "TQBR"))
    if subcommand == "orderbook":
        return get_order_book(cfg, args["ticker"], args.get("class_code", "TQBR"))
    raise BcsError(f"unknown market subcommand: {subcommand}")
