from __future__ import annotations

from typing import Any

from src.config import MACRO_SCENARIO_RULES


def select_scenario(
    key_rate: float,
    inflation: float,
    ruonia: float,
    gdp_growth: float,
    ofz_short_yield: float = 0.0,
    previous_key_rate: float = 0.0,
    unemployment: float = 2.6,
) -> dict[str, Any]:
    rate_change = key_rate - previous_key_rate
    is_hiking = rate_change > MACRO_SCENARIO_RULES.get("rate_cut_min_bps", 100) / 10000
    is_cutting = rate_change < -MACRO_SCENARIO_RULES.get("rate_cut_min_bps", 100) / 10000
    high_inflation = inflation > 0.07
    high_rate = key_rate > 0.12
    recession = gdp_growth < -0.01

    scenarios: dict[str, int] = {}
    if is_hiking:
        scenarios["hiking"] = 8
    if is_cutting:
        scenarios["cutting"] = 8
    if high_inflation or high_rate:
        scenarios["hawkish_stance"] = 6
    if recession:
        scenarios["recession"] = 7
    if not is_hiking and not is_cutting and not high_inflation and not recession:
        scenarios["stable"] = 4
    if gdp_growth > 0.03 and inflation < 0.05:
        scenarios["expansion"] = 5
    if not is_hiking and high_inflation:
        scenarios["stagflation"] = 5

    if not scenarios:
        scenarios["stable"] = 4

    best = max(scenarios, key=scenarios.get)
    best_score = scenarios[best]

    return {
        "selectedScenario": best,
        "score": best_score,
        "rating": _rating(best_score),
        "allScores": scenarios,
        "details": f"КС={key_rate*100:.0f}%, инфл={inflation*100:.1f}%, ВВП={gdp_growth*100:+.1f}%",
        "keyRate": round(key_rate, 2),
        "inflation": round(inflation, 2),
        "ruonia": round(ruonia, 2),
    }


def _rating(score: int) -> str:
    if score >= 8:
        return "aggressive"
    if score >= 5:
        return "defensive"
    return "neutral"
