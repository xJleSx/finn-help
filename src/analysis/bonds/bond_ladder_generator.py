from __future__ import annotations

from datetime import date
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

TARGET_LADDER_YEARS = [1, 2, 3, 5, 7, 10]


def generate_ladder(
    positions: list[dict[str, Any]],
    portfolio_value: float | None = None,
    target_allocation_per_year: float | None = None,
) -> dict[str, Any]:
    if not positions:
        return {
            "currentLadder": [],
            "gaps": [],
            "reinvestmentSuggestions": [],
            "summary": _empty_ladder_summary(),
        }

    total_value = portfolio_value or sum(p.get("totalValue", 0) or 0 for p in positions)
    today = date.today()

    ladder: dict[int, list[dict[str, Any]]] = {}
    for pos in positions:
        mat_str = pos.get("maturityDate") or ""
        if not mat_str:
            continue
        try:
            mat_date = date.fromisoformat(mat_str) if isinstance(mat_str, str) else mat_str
            yr = mat_date.year
        except (ValueError, TypeError):
            continue
        if yr not in ladder:
            ladder[yr] = []
        ladder[yr].append({
            "ticker": pos.get("ticker", "?"),
            "name": pos.get("name", pos.get("ticker", "?")),
            "maturityDate": mat_str if isinstance(mat_str, str) else mat_str.isoformat(),
            "value": pos.get("totalValue", 0) or 0,
            "ytm": pos.get("ytm", 0) or 0,
            "rating": pos.get("rating", "NR"),
            "couponYield": pos.get("couponYield", 0) or 0,
        })

    # Build current ladder representation
    current_ladder = []
    for year in sorted(ladder.keys()):
        bonds = ladder[year]
        total_year_value = sum(b["value"] for b in bonds)
        current_ladder.append({
            "year": year,
            "bonds": bonds,
            "totalValue": round(total_year_value, 2),
            "pctOfPortfolio": round(total_year_value / total_value * 100, 1) if total_value > 0 else 0,
        })

    # Find gaps in target ladder years
    current_years = set(ladder.keys())
    gaps = []
    for target_yr in TARGET_LADDER_YEARS:
        target_year = today.year + target_yr
        occupied = [y for y in current_years if abs(y - target_year) <= 1]
        if not occupied:
            gaps.append({
                "targetYear": target_year,
                "yearsFromNow": target_yr,
                "reason": f"Нет погашений в {target_year} году (+{target_yr} лет от сегодня)",
            })

    # Reinvestment suggestions for bonds maturing within 6 months
    maturing_soon = []
    for yr, bonds in ladder.items():
        for b in bonds:
            try:
                mat_date = date.fromisoformat(b["maturityDate"])
            except (ValueError, TypeError):
                continue
            days_to_maturity = (mat_date - today).days
            if 0 <= days_to_maturity <= 180:
                maturing_soon.append({**b, "daysToMaturity": days_to_maturity, "maturityYear": yr})

    reinvestment_suggestions = []
    for b in maturing_soon:
        target_yr = min(
            TARGET_LADDER_YEARS,
            key=lambda ty: abs((today.year + ty) - b["maturityYear"]),
        )
        target_year = today.year + target_yr
        reinvestment_suggestions.append({
            "maturingTicker": b["ticker"],
            "maturityDate": b["maturityDate"],
            "daysToMaturity": b["daysToMaturity"],
            "expectedValue": round(b["value"], 2),
            "suggestedHorizon": f"+{target_yr} лет",
            "suggestedTargetYear": target_year,
            "note": f"Реинвестировать в облигацию с погашением ~{target_year} года для заполнения лестницы",
        })

    per_year_target = target_allocation_per_year or (total_value / max(len(TARGET_LADDER_YEARS), 1))
    avg_ytm = _weighted_avg([b["ytm"] for b in sum(ladder.values(), [])],
                            [b["value"] for b in sum(ladder.values(), [])])
    total_ladder_value = sum(b["value"] for b in sum(ladder.values(), []))

    summary = {
        "totalLadderValue": round(total_ladder_value, 2),
        "pctOfPortfolioInLadder": round(total_ladder_value / total_value * 100, 1) if total_value > 0 else 0,
        "avgYtm": round(avg_ytm, 2),
        "gapCount": len(gaps),
        "maturingSoonCount": len(maturing_soon),
        "suggestedAllocationPerYear": round(per_year_target, 2),
        "ladderYearsCovered": sorted(ladder.keys()),
    }

    return {
        "currentLadder": current_ladder,
        "gaps": gaps,
        "reinvestmentSuggestions": reinvestment_suggestions,
        "summary": summary,
    }


def suggest_ladder_fill(
    available_bonds: list[dict[str, Any]],
    current_ladder: list[dict[str, Any]],
    portfolio_size: float,
) -> list[dict[str, Any]]:
    current_years = set()
    for rung in current_ladder:
        current_years.add(rung.get("year", 0))

    suggestions = []
    for bond in available_bonds:
        mat_str = bond.get("maturity_date") or bond.get("maturityDate")
        if not mat_str:
            continue
        try:
            yr = date.fromisoformat(mat_str).year if isinstance(mat_str, str) else mat_str.year
        except (ValueError, TypeError):
            continue
        if yr not in current_years:
            is_gap = any(
                abs(yr - target_yr) <= 1
                for target_yr in [date.today().year + ty for ty in TARGET_LADDER_YEARS]
            )
            if is_gap:
                max_position = portfolio_size * 0.25
                suggestions.append({
                    "ticker": bond.get("ticker", "?"),
                    "maturityYear": yr,
                    "ytm": bond.get("yield_to_maturity") or bond.get("ytm", 0),
                    "rating": bond.get("credit_rating") or bond.get("rating", "NR"),
                    "suggestedAmount": round(min(max_position, portfolio_size / len(TARGET_LADDER_YEARS)), 2),
                    "reason": f"Заполняет пробел в {yr} году лестницы погашений",
                })

    suggestions.sort(key=lambda s: (
        -TARGET_LADDER_YEARS.index(s["maturityYear"] - date.today().year)
        if (s["maturityYear"] - date.today().year) in TARGET_LADDER_YEARS
        else 99,
        -(s["ytm"] or 0),
    ))
    return suggestions


def _weighted_avg(values: list[float], weights: list[float]) -> float:
    if not values or not weights:
        return 0.0
    total_weight = sum(abs(w) for w in weights)
    if total_weight == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_weight


def _empty_ladder_summary() -> dict[str, Any]:
    return {
        "totalLadderValue": 0,
        "pctOfPortfolioInLadder": 0,
        "avgYtm": 0,
        "gapCount": 0,
        "maturingSoonCount": 0,
        "suggestedAllocationPerYear": 0,
        "ladderYearsCovered": [],
    }
