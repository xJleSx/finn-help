"""FinanceMarker API CLI entry point.

Subcommand-based CLI built on argparse. The agent invokes this script
through `bash` and parses JSON output (`--format json`, the default).
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

from financemarker import __version__
from financemarker.logging_setup import setup

log = logging.getLogger("fmc")


# ---------- output helpers ----------


def emit(data: Any, fmt: str) -> int:
    if fmt == "json":
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return 0
    if fmt == "human":
        from financemarker.formatters import to_human

        sys.stdout.write(to_human(data))
        sys.stdout.write("\n")
        return 0
    log.error("unknown format: %s", fmt)
    return 2


def _add_pagination_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--limit", type=int, default=30, help="page size (max 100)")
    p.add_argument("--offset", type=int, default=0, help="page offset")
    p.add_argument("--sort-by", help="field to sort by")
    p.add_argument(
        "--sort-order", choices=("ASC", "DESC"), help="sort direction"
    )
    p.add_argument(
        "--updated-in-days",
        type=int,
        help="only records updated in the last N days",
    )


# ---------- parser ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fmc",
        description="FinanceMarker.ru API CLI — fundamental data for public companies",
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
        help="DEBUG/INFO/WARN/ERROR (overrides .env FMC_LOG_LEVEL)",
    )
    p.add_argument("--version", action="version", version=f"fmc {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("token", help="show token status and remaining daily quota")

    s_stocks = sub.add_parser("stocks", help="list companies")
    _add_pagination_args(s_stocks)

    s_stock = sub.add_parser("stock", help="company detail (info + optional sections)")
    s_stock.add_argument("ref", help="EXCHANGE:CODE, e.g. MOEX:SBER")
    s_stock.add_argument(
        "--include",
        help=(
            "comma-separated sections to include: info,ratios,dividends,"
            "summary,reports,owners,shares,insiderTransactions,ideas,operations"
        ),
    )

    s_div = sub.add_parser("dividends", help="dividend calendar")
    s_div.add_argument(
        "--mode",
        choices=("upcoming", "past"),
        default="upcoming",
        help="upcoming (default) or past dividends",
    )
    _add_pagination_args(s_div)

    s_cal = sub.add_parser("calendar", help="upcoming corporate events")
    _add_pagination_args(s_cal)

    s_idea = sub.add_parser("ideas", help="active analyst ideas")
    _add_pagination_args(s_idea)

    s_idead = sub.add_parser("idea", help="analyst idea detail")
    s_idead.add_argument("id", type=int, help="idea id")

    s_ins = sub.add_parser("insiders", help="insider transactions")
    _add_pagination_args(s_ins)

    s_exp = sub.add_parser("experts", help="analyst leaderboard")
    _add_pagination_args(s_exp)

    s_disc = sub.add_parser("disclosure", help="corporate disclosures")
    _add_pagination_args(s_disc)

    sub.add_parser("exchanges", help="list supported exchanges")
    sub.add_parser("operation-metrics", help="operation-metric catalogue")

    s_resolve = sub.add_parser("resolve", help="resolve cached ticker name")
    s_resolve.add_argument("ref", help="EXCHANGE:CODE")

    return p


# ---------- dispatch ----------


def dispatch(args: argparse.Namespace) -> tuple[int, Any]:
    from financemarker.config import load_config
    from financemarker.errors import FmcError

    cfg = load_config()
    try:
        cmd = args.command

        if cmd == "token":
            from financemarker.token import get_token_info

            info = get_token_info(cfg)
            return 0, {
                "ok": True,
                "quota": {
                    "day_limit": info.get("day_limit"),
                    "valid_to": info.get("valid_to"),
                },
                "masked_token": cfg.mask_token(),
            }

        if cmd == "stocks":
            from financemarker.stocks import list_stocks

            return 0, list_stocks(
                cfg,
                limit=args.limit,
                offset=args.offset,
                sort_by=args.sort_by,
                sort_order=args.sort_order,
                updated_in_days=args.updated_in_days,
            )

        if cmd == "stock":
            from financemarker.stocks import get_stock, parse_stock_ref

            exchange, code = parse_stock_ref(args.ref)
            return 0, get_stock(
                cfg, exchange, code, include=args.include
            )

        if cmd == "dividends":
            from financemarker.events import list_dividends

            return 0, list_dividends(
                cfg,
                mode=args.mode,
                limit=args.limit,
                offset=args.offset,
                sort_by=args.sort_by,
                sort_order=args.sort_order,
                updated_in_days=args.updated_in_days,
            )

        if cmd == "calendar":
            from financemarker.events import list_calendar

            return 0, list_calendar(
                cfg,
                limit=args.limit,
                offset=args.offset,
                sort_by=args.sort_by,
                sort_order=args.sort_order,
            )

        if cmd == "ideas":
            from financemarker.research import list_ideas

            return 0, list_ideas(
                cfg,
                limit=args.limit,
                offset=args.offset,
                sort_by=args.sort_by,
                sort_order=args.sort_order,
                updated_in_days=args.updated_in_days,
            )

        if cmd == "idea":
            from financemarker.research import get_idea

            return 0, get_idea(cfg, args.id)

        if cmd == "insiders":
            from financemarker.research import list_insiders

            return 0, list_insiders(
                cfg,
                limit=args.limit,
                offset=args.offset,
                sort_by=args.sort_by,
                sort_order=args.sort_order,
                updated_in_days=args.updated_in_days,
            )

        if cmd == "experts":
            from financemarker.research import list_experts

            return 0, list_experts(
                cfg,
                limit=args.limit,
                offset=args.offset,
                sort_by=args.sort_by,
                sort_order=args.sort_order,
                updated_in_days=args.updated_in_days,
            )

        if cmd == "disclosure":
            from financemarker.research import list_disclosure

            return 0, list_disclosure(
                cfg,
                limit=args.limit,
                offset=args.offset,
                sort_by=args.sort_by,
                sort_order=args.sort_order,
            )

        if cmd == "exchanges":
            from financemarker.reference import list_exchanges

            return 0, list_exchanges(cfg)

        if cmd == "operation-metrics":
            from financemarker.reference import list_operation_metrics

            return 0, list_operation_metrics(cfg)

        if cmd == "resolve":
            from financemarker.cache import resolve_name

            from financemarker.stocks import parse_stock_ref

            exchange, code = parse_stock_ref(args.ref)
            name = resolve_name(exchange, code)
            return 0, {"exchange": exchange, "code": code, "name": name}

        raise FmcError(f"unknown command: {cmd}")
    except FmcError as e:
        return e.code, {"error": e.__class__.__name__, "message": str(e)}


def main(argv: Sequence[str] | None = None) -> int:
    from financemarker.errors import FmcError

    parser = build_parser()
    args = parser.parse_args(argv)
    setup(level=args.log_level)
    try:
        code, payload = dispatch(args)
    except FmcError as e:
        log.error("%s: %s", e.__class__.__name__, e)
        return e.code
    if payload is not None:
        emit(payload, args.format)
    return code


if __name__ == "__main__":
    sys.exit(main())
