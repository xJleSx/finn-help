from __future__ import annotations

from typing import Optional

from src.config import SPREAD_REJECT_THRESHOLDS


def estimate_spread(
    ticker: Optional[str] = None,
    rating: Optional[str] = None,
    sector: Optional[str] = None,
    years_to_maturity: float = 0,
    volume: Optional[float] = None,
) -> dict:
    base = _rate_spread(rating, sector)
    if years_to_maturity > 5:
        base *= 1.2
    elif years_to_maturity < 1:
        base *= 0.8
    if volume and volume < 10_000_000:
        base *= 1.3
    max_spread = SPREAD_REJECT_THRESHOLDS.get("max_acceptable_spread", 3.0)
    capped = min(base, max_spread)
    return {
        "spreadPct": round(capped, 2),
        "estimatedTick": ticker or "",
        "ratingUsed": rating or "NR",
        "maxAcceptable": max_spread,
        "rejectAbove": SPREAD_REJECT_THRESHOLDS.get("reject_above_pct", 5.0),
    }


def _rate_spread(rating: Optional[str], sector: Optional[str]) -> float:
    if rating:
        r = rating.upper()
        if r.startswith("AA") or r.startswith("AAA"):
            return 0.15
        if r.startswith("A"):
            return 0.25
        if r.startswith("BBB"):
            return 0.35
        if r.startswith("BB"):
            return 0.60
        if r.startswith("B"):
            return 1.00
        if r.startswith("CCC"):
            return 1.50
        if r.startswith("D"):
            return 3.00
    if sector == "government":
        return 0.08
    return 0.30
