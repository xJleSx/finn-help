"""Orders: list, place, edit, cancel.

`place`/`edit`/`cancel` are blocked in read-only mode at the CLI
dispatcher level. This module still validates payloads and never logs
the full request body to avoid leaking prices into a shared log.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .auth import auth_header
from .config import Config
from .endpoints import (
    OPERATIONS_BFF,
    ORDERS_SEARCH_URL,
    ORDER_CANCEL_URL_TPL,
    ORDER_GET_URL_TPL,
)
from .errors import BcsError, InvalidRequest
from .http_client import request_json

log = logging.getLogger("bcs_trade.orders")


def list_orders(
    cfg: Config,
    *,
    days: int = 7,
    ticker: str | None = None,
    side: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "startDateTime": (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z"),
        "endDateTime": now.strftime("%Y-%m-%dT23:59:59.000Z"),
    }
    if ticker:
        body["tickers"] = [ticker]
    if side:
        side_map = {"buy": 1, "sell": 2}
        body["side"] = side_map.get(side.lower(), side)
    if status:
        status_map = {"new": [1], "executed": [2], "partial": [3], "cancelled": [4], "rejected": [5]}
        body["orderStatus"] = status_map.get(status.lower(), [status])
    return request_json(
        "POST",
        ORDERS_SEARCH_URL,
        json_body=body,
        auth_header=auth_header(cfg),
    )


def get_order(cfg: Config, order_id: str) -> dict[str, Any]:
    url = ORDER_GET_URL_TPL.format(order_id=order_id)
    return request_json("GET", url, auth_header=auth_header(cfg))


def place_order(
    cfg: Config,
    *,
    ticker: str,
    side: str,
    type_: str,
    qty: int,
    price: float | None,
    account: str | None,
) -> dict[str, Any]:
    if qty <= 0:
        raise InvalidRequest("qty must be > 0")
    if type_ == "limit" and price is None:
        raise InvalidRequest("limit orders require --price")
    body: dict[str, Any] = {
        "ticker": ticker,
        "side": side,
        "type": type_,
        "quantity": qty,
    }
    if price is not None:
        body["price"] = price
    if account or cfg.account:
        body["account"] = account or cfg.account
    log.info("place order ticker=%s side=%s type=%s qty=%s", ticker, side, type_, qty)
    url = f"{OPERATIONS_BFF}/api/v1/orders"
    return request_json(
        "POST",
        url,
        json_body=body,
        auth_header=auth_header(cfg),
    )


def edit_order(
    cfg: Config,
    order_id: str,
    *,
    price: float | None,
    qty: int | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if price is not None:
        body["price"] = price
    if qty is not None:
        body["quantity"] = qty
    if not body:
        raise InvalidRequest("edit requires --price and/or --qty")
    url = ORDER_GET_URL_TPL.format(order_id=order_id)
    return request_json(
        "PUT",
        url,
        json_body=body,
        auth_header=auth_header(cfg),
    )


def cancel_order(cfg: Config, order_id: str, client_order_id: str | None = None) -> dict[str, Any]:
    url = ORDER_CANCEL_URL_TPL.format(order_id=order_id)
    body: dict[str, Any] = {}
    if client_order_id:
        body["clientOrderId"] = client_order_id
    return request_json(
        "POST",
        url,
        json_body=body if body else None,
        auth_header=auth_header(cfg),
    )


def run(subcommand: str, args: dict, cfg: Config) -> dict[str, Any]:
    if subcommand == "list":
        return list_orders(
            cfg,
            days=args.get("days", 7),
            ticker=args.get("ticker"),
            side=args.get("side"),
            status=args.get("status"),
        )
    if subcommand == "get":
        return get_order(cfg, args["order_id"])
    if subcommand == "place":
        return place_order(
            cfg,
            ticker=args["ticker"],
            side=args["side"],
            type_=args["type"],
            qty=args["qty"],
            price=args.get("price"),
            account=args.get("account"),
        )
    if subcommand == "edit":
        return edit_order(
            cfg, args["order_id"], price=args.get("price"), qty=args.get("qty")
        )
    if subcommand == "cancel":
        return cancel_order(cfg, args["order_id"], args.get("client_order_id"))
    raise BcsError(f"unknown orders subcommand: {subcommand}")
