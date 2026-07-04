"""BCS Trade API CLI entry point.

Subcommand-based CLI built on argparse. The agent invokes this script
through `bash` and parses JSON output (`--format json`, the default).
Human-readable output (`--format human`) is meant for the final answer
to the user.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from typing import Any, Sequence

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

from bcs_trade import __version__
from bcs_trade.logging_setup import setup

log = logging.getLogger("bcs")


# ---------- output helpers ----------


def emit(data: Any, fmt: str) -> int:
    """Emit a result according to --format. Returns process exit code."""
    if fmt == "json":
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return 0
    if fmt == "human":
        from bcs_trade.formatters import to_human

        sys.stdout.write(to_human(data))
        sys.stdout.write("\n")
        return 0
    log.error("unknown format: %s", fmt)
    return 2


# ---------- subcommand wiring ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bcs",
        description="BCS Trade API CLI — wrap https://trade-api.bcs.ru/",
    )
    p.add_argument(
        "--format",
        choices=("json", "human"),
        default="json",
        help="output format (default: json)",
    )
    p.add_argument(
        "--log-level",
        default=None,
        help="DEBUG/INFO/WARN/ERROR (overrides .env BCS_LOG_LEVEL)",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"bcs {__version__}",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # auth
    auth = sub.add_parser("auth", help="authentication management")
    auth_sub = auth.add_subparsers(dest="subcommand", required=True)
    auth_sub.add_parser("status", help="show current token state")
    auth_sub.add_parser("login", help="exchange refresh token for access token")

    # portfolio
    port = sub.add_parser("portfolio", help="current portfolio")
    port.add_argument("--account", help="account id (default: BCS_ACCOUNT)")
    port.add_argument(
        "--term",
        default="T0",
        choices=("T0", "T1", "T2", "T365"),
        help="settlement term; T0 = live position (default), "
             "T1/T2/T365 = planned future settlements (over-counts by 4×)",
    )
    sub.add_parser("limits", help="limits / cash / margin")

    # market
    market = sub.add_parser("market", help="market data and reference")
    market_sub = market.add_subparsers(dest="subcommand", required=True)
    q = market_sub.add_parser("quote", help="last quote for a ticker")
    q.add_argument("ticker", help="instrument ticker, e.g. SBER")
    q.add_argument("--class-code", default="TQBR", help="class code (default: TQBR)")
    s = market_sub.add_parser("search", help="search instrument by ticker")
    s.add_argument("query", help="ticker to look up, e.g. SBER")
    ibt = market_sub.add_parser("by-type", help="list instruments by type")
    ibt.add_argument("type", help="instrument type: STOCK, BOND, ETF, etc.")
    ibt.add_argument("--page", type=int, default=0)
    ibt.add_argument("--size", type=int, default=50)
    c = market_sub.add_parser("candles", help="historical candles for a ticker")
    c.add_argument("ticker")
    c.add_argument("--class-code", default="TQBR")
    ob = market_sub.add_parser("orderbook", help="current order book")
    ob.add_argument("ticker")
    ob.add_argument("--class-code", default="TQBR")

    # schedule
    sched = sub.add_parser("schedule", help="trading schedule")
    sched_sub = sched.add_subparsers(dest="subcommand", required=True)
    st = sched_sub.add_parser("today", help="today's trading schedule")
    st.add_argument("--ticker", default="SBER", help="ticker (default: SBER)")
    st.add_argument("--class-code", default="TQBR", help="class code (default: TQBR)")
    ss = sched_sub.add_parser("status", help="current trading status")
    ss.add_argument("--class-code", default="TQBR", help="class code (default: TQBR)")

    # orders
    orders = sub.add_parser("orders", help="orders (list/place/edit/cancel)")
    orders_sub = orders.add_subparsers(dest="subcommand", required=True)
    ol = orders_sub.add_parser("list", help="list recent orders")
    ol.add_argument("--days", type=int, default=7, help="lookback days (default: 7)")
    ol.add_argument("--ticker", help="filter by ticker")
    ol.add_argument("--side", choices=("buy", "sell"), help="filter by side")
    ol.add_argument("--status", choices=("new", "executed", "partial", "cancelled", "rejected"), help="filter by status")
    og = orders_sub.add_parser("get", help="get order by ID")
    og.add_argument("order_id", help="order ID (e.g. 260610-TQBR-80045952311)")
    place = orders_sub.add_parser("place", help="place a new order")
    place.add_argument("--ticker", required=True)
    place.add_argument("--side", choices=("buy", "sell"), required=True)
    place.add_argument("--type", choices=("market", "limit"), required=True)
    place.add_argument("--qty", type=int, required=True, help="quantity (lots)")
    place.add_argument("--price", type=float, help="limit price")
    place.add_argument("--account", help="account id (default: BCS_ACCOUNT)")
    edit = orders_sub.add_parser("edit", help="edit an existing order")
    edit.add_argument("order_id")
    edit.add_argument("--price", type=float)
    edit.add_argument("--qty", type=int)
    cancel = orders_sub.add_parser("cancel", help="cancel an order")
    cancel.add_argument("order_id", help="order ID")
    cancel.add_argument("--client-order-id", help="client order ID (if known)")

    # trades
    trades = sub.add_parser("trades", help="trades / fills")
    trades_sub = trades.add_subparsers(dest="subcommand", required=True)
    tl = trades_sub.add_parser("list", help="list recent trades")
    tl.add_argument("--days", type=int, default=7, help="lookback days (default: 7)")
    tl.add_argument("--ticker", help="filter by ticker")

    # snapshot
    snap = sub.add_parser("snapshot", help="portfolio snapshots (SQLite)")
    snap_sub = snap.add_subparsers(dest="subcommand", required=True)
    save = snap_sub.add_parser("save", help="snapshot current portfolio")
    save.add_argument(
        "--term",
        default="T0",
        choices=("T0", "T1", "T2", "T365"),
        help="settlement term; T0 = live (default)",
    )
    save.add_argument("--label", help="optional human-readable label")
    snap_sub.add_parser("list", help="list saved snapshots")

    # moex (MOEX ISS — free, no auth)
    moex = sub.add_parser("moex", help="MOEX ISS data (free, 15-min delay)")
    moex_sub = moex.add_subparsers(dest="subcommand", required=True)
    ms = moex_sub.add_parser("security", help="security reference (ISIN, lot, etc.)")
    ms.add_argument("ticker", help="e.g. SBER")
    mq = moex_sub.add_parser("quote", help="market data (delayed 15 min)")
    mq.add_argument("ticker")
    mq.add_argument("--board", default="TQBR")
    mc = moex_sub.add_parser("candles", help="historical OHLCV candles")
    mc.add_argument("ticker")
    mc.add_argument("--from", dest="from_date", help="YYYY-MM-DD")
    mc.add_argument("--till", help="YYYY-MM-DD")
    mc.add_argument("--interval", type=int, default=24, help="1/5/10/15/30/60/24=1d")
    mc.add_argument("--limit", type=int, default=100)
    msp = moex_sub.add_parser("splits", help="split history")
    msp.add_argument("--ticker", help="filter by ticker")
    msp.add_argument("--limit", type=int, default=100)

    return p


# ---------- dispatch ----------


def dispatch(args: argparse.Namespace) -> tuple[int, Any]:
    """Run the chosen subcommand. Returns (exit_code, payload)."""
    from bcs_trade.errors import BcsError, InvalidRequest, ReadOnlyBlocked

    cmd, sub = args.command, getattr(args, "subcommand", None)

    # MOEX ISS doesn't need BCS auth
    if cmd == "moex":
        from bcs_trade.moex import run as moex_run

        try:
            return 0, moex_run(sub, vars(args))
        except BcsError as e:
            return e.code, {"error": e.__class__.__name__, "message": str(e)}

    from bcs_trade.config import load_config
    from bcs_trade.portfolio import dedupe_positions, filter_by_term

    cfg = load_config()

    try:
        cmd, sub = args.command, getattr(args, "subcommand", None)

        if cmd == "auth":
            from bcs_trade.auth import run as auth_run

            return 0, auth_run(sub, cfg)
        if cmd == "portfolio":
            from bcs_trade.portfolio import get_portfolio

            raw = get_portfolio(cfg, account=getattr(args, "account", None))
            term = getattr(args, "term", "T0")
            # BCS returns the same position under 4 settlement terms; we
            # filter to the chosen term and drop board-level duplicates.
            payload = dedupe_positions(filter_by_term(raw, term=term))
            return 0, payload
        if cmd == "limits":
            from bcs_trade.portfolio import get_limits

            return 0, get_limits(cfg)
        if cmd == "market":
            from bcs_trade.market import run as market_run

            return 0, market_run(sub, vars(args), cfg)
        if cmd == "schedule":
            from bcs_trade.schedule import run as schedule_run

            return 0, schedule_run(sub, vars(args), cfg)
        if cmd == "orders":
            if sub in ("place", "cancel", "edit") and cfg.read_only:
                raise ReadOnlyBlocked(sub)
            from bcs_trade.orders import run as orders_run

            return 0, orders_run(sub, vars(args), cfg)
        if cmd == "trades":
            from bcs_trade.trades import run as trades_run

            return 0, trades_run(sub, vars(args), cfg)
        if cmd == "snapshot":
            from bcs_trade.cache import save_portfolio_snapshot

            if sub == "save":
                return 0, save_portfolio_snapshot(
                    cfg,
                    label=getattr(args, "label", None),
                    term=getattr(args, "term", "T0"),
                )
            from bcs_trade.cache import run as snapshot_run

            return 0, snapshot_run(sub, cfg)

        raise InvalidRequest(f"unknown command: {cmd}/{sub}")
    except BcsError as e:
        return e.code, {"error": e.__class__.__name__, "message": str(e)}


def main(argv: Sequence[str] | None = None) -> int:
    from bcs_trade.errors import BcsError

    parser = build_parser()
    args = parser.parse_args(argv)
    setup(level=args.log_level)
    try:
        code, payload = dispatch(args)
    except BcsError as e:
        log.error("%s: %s", e.__class__.__name__, e)
        return e.code
    if payload is not None:
        emit(payload, args.format)
    return code


if __name__ == "__main__":
    sys.exit(main())
