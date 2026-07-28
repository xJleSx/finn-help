from __future__ import annotations

from typing import Any, Optional

from src.config import DEFAULT_PROBABILITY_BY_RATING


def get_default_probability(
    rating: str,
    years_to_maturity: float = 1.0,
    sector: Optional[str] = None,
    has_state_support: bool = False,
) -> dict[str, Any]:
    base_prob = DEFAULT_PROBABILITY_BY_RATING.get(rating.upper(), 0.90)

    if years_to_maturity > 5:
        base_prob += 0.05
    elif years_to_maturity > 3:
        base_prob += 0.02
    elif years_to_maturity < 1:
        base_prob -= 0.01

    if has_state_support:
        base_prob = max(base_prob * 0.3, 0.99)
    elif sector:
        sector_lower = sector.lower()
        if sector_lower in ("oil & gas", "energy", "government"):
            base_prob = max(base_prob - 0.02, 0.95)
        elif sector_lower in ("retail", "real estate", "construction"):
            base_prob = min(base_prob + 0.03, 1.0)

    base_prob = max(0.50, min(base_prob, 1.0))

    return {
        "rating": rating,
        "defaultProbability": round(base_prob, 4),
        "survivalProbability": round(1 - base_prob, 4),
        "yearsToMaturity": years_to_maturity,
        "dataSource": "DEFAULT_PROBABILITY_BY_RATING (эмитент-статистика)",
    }
