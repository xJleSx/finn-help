"""Lightweight response models.

We keep this module small on purpose: BCS responses are heterogeneous
and we don't want a heavy schema layer. These dataclasses exist mainly
to document the *shape* the rest of the package expects.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Position:
    ticker: str
    name: str | None
    quantity: float
    avg_price: float | None
    last_price: float | None
    cost: float | None

    @classmethod
    def from_api(cls, raw: dict) -> "Position":
        return cls(
            ticker=raw.get("ticker") or raw.get("secId") or "",
            name=raw.get("name"),
            quantity=float(raw.get("quantity", 0) or 0),
            avg_price=_maybe_float(raw.get("avgPrice")),
            last_price=_maybe_float(raw.get("lastPrice") or raw.get("price")),
            cost=_maybe_float(raw.get("cost") or raw.get("evaluation")),
        )


@dataclass(slots=True)
class Order:
    order_id: str
    ticker: str
    side: str
    qty: int
    price: float | None
    status: str

    @classmethod
    def from_api(cls, raw: dict) -> "Order":
        return cls(
            order_id=str(raw.get("orderId") or raw.get("id") or ""),
            ticker=raw.get("ticker") or raw.get("secId") or "",
            side=str(raw.get("side") or raw.get("direction") or ""),
            qty=int(raw.get("qty") or raw.get("quantity") or 0),
            price=_maybe_float(raw.get("price")),
            status=str(raw.get("status") or ""),
        )


def _maybe_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
