from __future__ import annotations

from typing import Any, Optional

from src.analysis.bonds_math import compute_put_adjusted_duration, put_exercise_probability


def valuate_put_option(
    has_offer: bool,
    modified_duration: Optional[float] = None,
    years_to_maturity: Optional[float] = None,
    years_to_put: Optional[float] = None,
    coupon_rate: Optional[float] = None,
    ytm: Optional[float] = None,
    convexity: Optional[float] = None,
    current_price: float = 1000.0,
    nominal: float = 1000.0,
    rate_change_delta: float = 0.02,
    ytm_with_put: Optional[float] = None,
    ytm_without_put: Optional[float] = None,
    rate_cycle_phase: str = "stable",
) -> dict[str, Any]:
    if not has_offer:
        return {
            "hasPut": False,
            "putValue": 0.0,
            "protectionPct": 0.0,
            "priceDropWithoutPut": 0.0,
            "priceDropWithPut": 0.0,
        }

    mod_dur = modified_duration or 0.0
    conv = convexity or 0.0

    p_exercise = put_exercise_probability(coupon_rate=coupon_rate, ytm=ytm)
    effective_dur = compute_put_adjusted_duration(
        mod_dur,
        years_to_maturity or 1.0,
        years_to_put,
        p_exercise,
    )

    price_drop_linear = -mod_dur * rate_change_delta * current_price
    convexity_adjustment = 0.5 * conv * (rate_change_delta ** 2) * current_price
    price_drop_with_convexity = price_drop_linear + convexity_adjustment

    put_protection = max(0, nominal - current_price)

    put_cost_annualized = None
    if ytm_with_put is not None and ytm_without_put is not None:
        put_cost_annualized = ytm_without_put - ytm_with_put

    scenario_label = _get_scenario_label(rate_cycle_phase, rate_change_delta)

    return {
        "hasPut": True,
        "putValue": round(put_protection, 2),
        "protectionPct": round(put_protection / current_price * 100, 2) if current_price > 0 else 0,
        "priceDropWithoutPutLinear": round(price_drop_linear, 2),
        "priceDropWithConvexity": round(price_drop_with_convexity, 2),
        "priceDropWithPut": round(min(price_drop_with_convexity, 0) + put_protection, 2),
        "insuranceCostAnnualized": round(put_cost_annualized, 2) if put_cost_annualized is not None else None,
        "scenario": scenario_label,
        "rateChangeDelta": rate_change_delta,
        "effectiveDurationWithPut": round(effective_dur, 2),
        "putExerciseProbability": round(p_exercise, 2),
    }


def _get_scenario_label(rate_cycle_phase: str, rate_change_delta: float) -> str:
    if rate_change_delta > 0:
        direction = "рост"
    elif rate_change_delta < 0:
        direction = "снижение"
    else:
        direction = "стабильность"
    return f"{direction} ставки на {abs(rate_change_delta)*100:.0f} б.п. [{rate_cycle_phase}]"
