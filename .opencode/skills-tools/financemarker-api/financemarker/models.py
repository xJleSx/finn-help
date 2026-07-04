"""Lightweight response models.

We don't enforce schemas at runtime — FinanceMarker returns
heterogeneous shapes and we want to be permissive. These dataclasses
exist primarily as documentation and to give editors a place to
discover field names.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StockInfo:
    code: str
    exchange: str
    name: str | None
    country: str | None
    currency: str | None
    sector: str | None
    industry: str | None

    @classmethod
    def from_api(cls, raw: dict) -> "StockInfo":
        return cls(
            code=raw.get("code", ""),
            exchange=raw.get("exchange", ""),
            name=raw.get("name"),
            country=raw.get("country"),
            currency=raw.get("currency"),
            sector=raw.get("sector"),
            industry=raw.get("industry"),
        )


@dataclass(slots=True)
class StockSummary:
    code: str
    exchange: str
    capital: float | None
    pe: float | None
    roe: float | None
    dividend_yield_12m: float | None
    dividend_growth: int | None
    graham_target: float | None

    @classmethod
    def from_api(cls, raw: dict) -> "StockSummary":
        return cls(
            code=raw.get("code", ""),
            exchange=raw.get("exchange", ""),
            capital=_maybe_float(raw.get("capital")),
            pe=_maybe_float(raw.get("pe")),
            roe=_maybe_float(raw.get("roe")),
            dividend_yield_12m=_maybe_float(raw.get("dividend_yield_12m")),
            dividend_growth=_maybe_int(raw.get("dividend_growth")),
            graham_target=_maybe_float(raw.get("graham_target")),
        )


def _maybe_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _maybe_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
