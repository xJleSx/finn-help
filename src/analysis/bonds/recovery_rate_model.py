from __future__ import annotations

from typing import Optional

from src.config import RECOVERY_RATE_DEFAULTS


def estimate_recovery(
    rating: str,
    seniority: str = "unsecured",
    sector: Optional[str] = None,
    has_state_support: bool = False,
    collateral_type: Optional[str] = None,
    is_secured: bool = False,
) -> float:
    if has_state_support:
        base = RECOVERY_RATE_DEFAULTS.get("with_state_support", 66.7)
    elif is_secured or collateral_type:
        base = RECOVERY_RATE_DEFAULTS.get("secured", 65.0)
    else:
        base = RECOVERY_RATE_DEFAULTS.get("without_state_support", 40.0)

    if rating.upper() in ("AAA", "AA"):
        base = min(base + 10, 80)
    elif rating.upper() in ("BB", "B", "CCC"):
        base = max(base - 10, 10)
    elif rating.upper() in ("CC", "C", "D"):
        base = max(base - 20, 5)

    if sector:
        sector_lower = sector.lower()
        if sector_lower in ("oil & gas", "energy", "government"):
            base = min(base + 5, 85)
        elif sector_lower in ("retail", "real estate"):
            base = max(base - 5, 10)

    return round(base, 1)
