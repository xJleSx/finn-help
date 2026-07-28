from __future__ import annotations

from typing import Any, Optional

from src.analysis.bonds.recovery_rate_model import estimate_recovery
from src.config import DEFAULT_PROBABILITY_BY_RATING, KELLY_SIZER_LIMITS


def kelly_speculative_size(
    rating: str,
    ytm_speculative: float,
    ytm_risk_free: float,
    portfolio_value: float,
    sector: Optional[str] = None,
    has_state_support: bool = False,
    is_secured: bool = False,
) -> dict[str, Any]:
    p_default = 1.0 - DEFAULT_PROBABILITY_BY_RATING.get(rating.upper(), 0.90)
    p_no_default = 1.0 - p_default

    r_spec = ytm_speculative - ytm_risk_free
    if r_spec <= 0:
        return {
            "kellyFraction": 0.0,
            "cappedFraction": 0.0,
            "suggestedAmount": 0,
            "note": "Премия за риск отсутствует — не использовать",
            "rating": rating,
        }

    recovery = estimate_recovery(
        rating=rating,
        sector=sector,
        has_state_support=has_state_support,
        is_secured=is_secured,
    )

    numerator = (p_no_default * (1 + r_spec / 100)) - (p_default * (1 - recovery / 100))
    denominator = (r_spec / 100) + (recovery / 100)

    kelly_fraction = numerator / denominator if denominator > 0 else 0.0
    kelly_fraction = max(0.0, min(kelly_fraction, KELLY_SIZER_LIMITS["kelly_cap_pct"]))

    is_small = portfolio_value < KELLY_SIZER_LIMITS.get("small_portfolio_threshold", 50000)
    max_pct = KELLY_SIZER_LIMITS["small_portfolio_max_pct"] if is_small else KELLY_SIZER_LIMITS["large_portfolio_max_pct"]

    capped_fraction = min(kelly_fraction, max_pct)
    suggested_amount = portfolio_value * capped_fraction

    max_positions = KELLY_SIZER_LIMITS["max_speculative_positions_small"] if is_small else KELLY_SIZER_LIMITS["max_speculative_positions_large"]

    notes = []
    if kelly_fraction > max_pct:
        notes.append(f"Kelly ({kelly_fraction*100:.0f}%) превышает лимит {max_pct*100:.0f}% — применено ограничение")
    else:
        notes.append(f"Kelly ({kelly_fraction*100:.0f}%) в пределах лимита")

    return {
        "kellyFraction": round(kelly_fraction, 4),
        "cappedFraction": round(capped_fraction, 4),
        "suggestedAmount": round(suggested_amount, 2),
        "suggestedPct": round(capped_fraction * 100, 1),
        "pDefault": round(p_default, 4),
        "pNoDefault": round(p_no_default, 4),
        "recoveryRate": round(recovery, 1),
        "riskPremium": round(r_spec, 2),
        "maxPositionsAllowed": max_positions,
        "isSmallPortfolio": is_small,
        "notes": notes,
        "rating": rating,
    }
