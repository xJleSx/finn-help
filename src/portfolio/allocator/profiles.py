from __future__ import annotations

from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "conservative": {
        "bond": {"weight": 0.60, "label": "Облигации / ОФЗ", "max": 6},
        "etf": {"weight": 0.15, "label": "БПИФ (ETF)", "max": 2},
        "dividend": {"weight": 0.15, "label": "Дивидендные акции", "max": 2},
        "growth": {"weight": 0.10, "label": "Акции роста", "max": 2},
    },
    "balanced": {
        "etf": {"weight": 0.40, "label": "БПИФ (ETF)", "max": 3},
        "dividend": {"weight": 0.30, "label": "Дивидендные акции", "max": 4},
        "bond": {"weight": 0.20, "label": "Облигации / ОФЗ", "max": 3},
        "growth": {"weight": 0.10, "label": "Акции роста", "max": 2},
    },
    "aggressive": {
        "etf": {"weight": 0.25, "label": "БПИФ (ETF)", "max": 3},
        "dividend": {"weight": 0.25, "label": "Дивидендные акции", "max": 3},
        "bond": {"weight": 0.10, "label": "Облигации / ОФЗ", "max": 2},
        "growth": {"weight": 0.40, "label": "Акции роста", "max": 4},
    },
}


def get_profile(name: str) -> dict[str, Any]:
    profile = PROFILES.get(name, PROFILES["balanced"])
    total = sum(v["weight"] for v in profile.values())
    if abs(total - 1.0) > 1e-6:
        for v in profile.values():
            v["weight"] = v["weight"] / total
    return profile
