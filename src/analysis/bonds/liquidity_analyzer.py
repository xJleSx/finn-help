from __future__ import annotations

from typing import Any, Optional

from src.config import LIQUIDITY_THRESHOLDS


def analyze_liquidity(
    ticker: str,
    value_today: Optional[float] = None,
    num_trades: Optional[int] = None,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    bid_depth: Optional[int] = None,
    ask_depth: Optional[int] = None,
    amihud_ratio: Optional[float] = None,
    bond_type: str = "corporate",
    rating: Optional[str] = None,
) -> dict[str, Any]:
    thresholds = _get_thresholds(bond_type, rating)

    score = 0
    max_score = 0
    details: dict[str, Any] = {}
    warnings: list[str] = []

    if value_today is not None:
        max_score += 30
        if value_today >= thresholds.get("value_min_high", 100_000_000):
            score += 30
            details["valueLabel"] = "high"
        elif value_today >= thresholds.get("value_min_medium", 20_000_000):
            score += 20
            details["valueLabel"] = "medium"
        elif value_today > thresholds.get("value_max_low", 500_000):
            score += 10
            details["valueLabel"] = "low"
        else:
            details["valueLabel"] = "very_low"
            warnings.append(f"Дневной оборот {value_today:,.0f}₽ — низкая ликвидность")

    if bid is not None and ask is not None and bid > 0:
        max_score += 25
        spread_pct = (ask - bid) / ((ask + bid) / 2) * 100
        details["spreadPct"] = round(spread_pct, 3)
        spread_max = thresholds.get("spread_max", 1.0)
        if spread_pct <= spread_max * 0.5:
            score += 25
        elif spread_pct <= spread_max:
            score += 15
        else:
            warnings.append(f"Спред {spread_pct:.2f}% превышает порог {spread_max}%")

    if num_trades is not None:
        max_score += 20
        trades_min = thresholds.get("trades_min", 10)
        trades_max = thresholds.get("trades_max", 100)
        if num_trades >= trades_max:
            score += 20
        elif num_trades >= trades_min:
            score += 10
        else:
            warnings.append(f"Всего {num_trades} сделок/день — низкая активность")
        details["numTrades"] = num_trades

    depth_min = thresholds.get("depth_min", 10)
    if bid_depth is not None and ask_depth is not None:
        max_score += 15
        avg_depth = (bid_depth + ask_depth) / 2
        if avg_depth >= depth_min * 3:
            score += 15
        elif avg_depth >= depth_min:
            score += 8
        else:
            warnings.append(f"Глубина стакана {avg_depth:.0f} лотов — ниже порога {depth_min}")
        details["avgDepth"] = round(avg_depth, 1)

    if amihud_ratio is not None:
        max_score += 10
        amihud_max = thresholds.get("amihud_max", 0.1)
        if amihud_ratio <= amihud_max:
            score += 10
        else:
            warnings.append(f"Коэфф. Амихуда {amihud_ratio:.4f} — низкая ликвидность")
        details["amihudRatio"] = round(amihud_ratio, 4)

    liquidity_pct = (score / max_score * 100) if max_score > 0 else 0
    if liquidity_pct >= 80:
        liquidity_score = "high"
    elif liquidity_pct >= 50:
        liquidity_score = "medium"
    else:
        liquidity_score = "low"

    return {
        "ticker": ticker,
        "liquidityScore": liquidity_score,
        "liquidityPct": round(liquidity_pct, 1),
        "details": details,
        "warnings": warnings,
        "bondType": bond_type,
    }


def _get_thresholds(bond_type: str, rating: Optional[str] = None) -> dict[str, Any]:
    if bond_type == "ofz":
        return dict(LIQUIDITY_THRESHOLDS["ofz"])
    if rating and rating.upper().startswith("A"):
        return dict(LIQUIDITY_THRESHOLDS.get("corporate_aaa", LIQUIDITY_THRESHOLDS["corporate"]))
    return dict(LIQUIDITY_THRESHOLDS["corporate"])
