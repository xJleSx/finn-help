from __future__ import annotations

from typing import Any, Literal, Optional

RateCyclePhase = Literal["cutting", "hiking", "stable"]


def detect_rate_cycle(
    key_rate_history: list[dict[str, Any]] | None = None,
    lookback_months: int = 6,
    ruonia_history: list[dict[str, Any]] | None = None,
    ofz_short_level: float | None = None,
    cbr_rhetoric: str | None = None,
) -> dict[str, Any]:
    if not key_rate_history or len(key_rate_history) < 2:
        base = _default_cycle()
        base.update(_augment_cycle(ruonia_history, ofz_short_level, cbr_rhetoric))
        return base

    sorted_rates = sorted(key_rate_history, key=lambda x: x.get("date", x.get("Date", "")))
    recent = sorted_rates[-lookback_months:] if len(sorted_rates) > lookback_months else sorted_rates

    if len(recent) < 2:
        base = _default_cycle()
        base.update(_augment_cycle(ruonia_history, ofz_short_level, cbr_rhetoric))
        return base

    first_rate = _extract_rate(recent[0])
    last_rate = _extract_rate(recent[-1])

    if first_rate is None or last_rate is None:
        base = _default_cycle()
        base.update(_augment_cycle(ruonia_history, ofz_short_level, cbr_rhetoric))
        return base

    change = last_rate - first_rate
    change_pct = (change / first_rate * 100) if first_rate > 0 else 0.0
    months_span = len(recent)

    changes = []
    for i in range(1, len(recent)):
        prev = _extract_rate(recent[i - 1])
        curr = _extract_rate(recent[i])
        if prev is not None and curr is not None:
            changes.append(curr - prev)

    recent_down = sum(1 for c in changes[-3:] if c < -0.25) if len(changes) >= 3 else 0
    recent_up = sum(1 for c in changes[-3:] if c > 0.25) if len(changes) >= 3 else 0

    rhetoric_lower = cbr_rhetoric.lower() if cbr_rhetoric else ""

    if change < -1.0 or (change < -0.5 and recent_down >= 2):
        phase: RateCyclePhase = "cutting"
        label = "Снижение"
        description = "Цикл снижения ключевой ставки — длинные облигации с фиксированным купоном выигрывают"
        confidence_penalty = 0.2 if "повышение" in rhetoric_lower or "tight" in rhetoric_lower else 0.0
    elif change > 1.0 or (change > 0.5 and recent_up >= 2):
        phase = "hiking"
        label = "Повышение"
        description = "Цикл повышения ключевой ставки — флоатеры и короткие облигации предпочтительны"
        confidence_penalty = 0.2 if "снижение" in rhetoric_lower or "ease" in rhetoric_lower else 0.0
    else:
        phase = "stable"
        label = "Стабильная"
        description = "Ключевая ставка стабильна — стандартная стратегия"
        if "повышение" in rhetoric_lower or "tight" in rhetoric_lower:
            phase = "hiking"
            label = "Повышение (сигнал)"
            description += " Сигнал ЦБ указывает на возможное повышение."
        elif "снижение" in rhetoric_lower or "ease" in rhetoric_lower:
            phase = "cutting"
            label = "Снижение (сигнал)"
            description += " Сигнал ЦБ указывает на возможное снижение."
        confidence_penalty = 0.0

    confidence = min(abs(change) / 3.0, 1.0) if abs(change) > 0 else 0.3
    if abs(change) < 0.5:
        confidence = 0.3
    confidence = max(0.0, confidence - confidence_penalty)

    ruonia_spread = None
    if ruonia_history and len(ruonia_history) >= 2:
        ruonia_latest = _extract_rate(ruonia_history[-1])
        ruonia_earliest = _extract_rate(ruonia_history[0])
        if ruonia_latest is not None and ruonia_earliest is not None:
            ruonia_spread = round((ruonia_latest - ruonia_earliest) * 100, 1)

    return {
        "phase": phase,
        "direction": round(change, 2),
        "change_pct": round(change_pct, 2),
        "months_trend": months_span,
        "confidence": round(confidence, 2),
        "label": label,
        "description": description,
        "ruoniaSpreadBps": ruonia_spread,
        "ofzShortYield": round(ofz_short_level, 2) if ofz_short_level is not None else None,
        "cbrRhetoric": cbr_rhetoric,
        "correlationNote": _build_correlation_note(ruonia_spread, ofz_short_level, cbr_rhetoric),
    }


def _default_cycle() -> dict[str, Any]:
    return {
        "phase": "stable",
        "direction": 0.0,
        "change_pct": 0.0,
        "months_trend": 0,
        "confidence": 0.0,
        "label": "Стабильная",
        "description": "Недостаточно данных для определения цикла",
    }


def _augment_cycle(
    ruonia_history: list[dict[str, Any]] | None,
    ofz_short_level: float | None,
    cbr_rhetoric: str | None,
) -> dict[str, Any]:
    ruonia_spread = None
    if ruonia_history and len(ruonia_history) >= 2:
        ruonia_latest = _extract_rate(ruonia_history[-1])
        ruonia_earliest = _extract_rate(ruonia_history[0])
        if ruonia_latest is not None and ruonia_earliest is not None:
            ruonia_spread = round((ruonia_latest - ruonia_earliest) * 100, 1)
    return {
        "ruoniaSpreadBps": ruonia_spread,
        "ofzShortYield": round(ofz_short_level, 2) if ofz_short_level is not None else None,
        "cbrRhetoric": cbr_rhetoric,
        "correlationNote": _build_correlation_note(ruonia_spread, ofz_short_level, cbr_rhetoric),
    }


def _build_correlation_note(
    ruonia_spread: float | None,
    ofz_short_yield: float | None,
    cbr_rhetoric: str | None,
) -> str:
    parts = []
    if ruonia_spread is not None:
        direction = "растёт" if ruonia_spread > 0 else "снижается"
        parts.append(f"RUONIA {direction} ({ruonia_spread:+.0f} б.п.)")
    if ofz_short_yield is not None:
        parts.append(f"короткая ОФЗ {ofz_short_yield:.1f}%")
    if cbr_rhetoric:
        parts.append(f"сигнал ЦБ: {cbr_rhetoric[:40]}")
    return "; ".join(parts) if parts else ""


def _extract_rate(entry: dict[str, Any]) -> Optional[float]:
    for key in ("value", "rate", "key_rate", "Value", "Rate"):
        val = entry.get(key)
        if val is not None:
            return float(val)
    return None


def adjust_bond_score_for_rate_cycle(
    base_score: float,
    duration_years: float | None,
    coupon_type: str | None,
    rate_cycle: RateCyclePhase,
    has_offer: bool = False,
) -> tuple[float, list[str]]:
    adjustments: list[str] = []
    score = base_score

    if rate_cycle == "cutting":
        if duration_years and duration_years > 5:
            bonus = min((duration_years - 5) * 0.03, 0.25)
            score += bonus
            adjustments.append(f"Цикл снижения ставки: длинная дюрация ({duration_years:.1f}л) -> +{bonus:.2f}")
        elif duration_years and duration_years > 3:
            score += 0.10
            adjustments.append("Цикл снижения ставки: умеренная дюрация -> +0.10")

        if coupon_type and coupon_type.lower() in ("float", "floating", "floater"):
            score -= 0.15
            adjustments.append("Цикл снижения ставки: флоатер невыгоден -> -0.15")

        if coupon_type and coupon_type.lower() == "fixed":
            score += 0.10
            adjustments.append("Цикл снижения ставки: фиксированный купон -> +0.10")

        if has_offer:
            score += 0.05
            adjustments.append("Цикл снижения ставки: оферта даёт гибкость -> +0.05")

    elif rate_cycle == "hiking":
        if duration_years and duration_years > 5:
            penalty = min((duration_years - 5) * 0.04, 0.30)
            score -= penalty
            adjustments.append(f"Цикл повышения ставки: длинная дюрация ({duration_years:.1f}л) -> -{penalty:.2f}")
        elif duration_years and duration_years < 2:
            score += 0.10
            adjustments.append("Цикл повышения ставки: короткая дюрация -> +0.10")

        if coupon_type and coupon_type.lower() in ("float", "floating", "floater"):
            score += 0.20
            adjustments.append("Цикл повышения ставки: флоатер защищает -> +0.20")

        if has_offer:
            score += 0.10
            adjustments.append("Цикл повышения ставки: оферта — возможность выхода -> +0.10")

    else:
        if duration_years and duration_years > 7:
            score -= 0.05
            adjustments.append("Стабильный цикл: большая дюрация — умеренный риск -> -0.05")

    return score, adjustments


def get_rate_cycle_recommendation(rate_cycle: RateCyclePhase) -> dict[str, Any]:
    recommendations = {
        "cutting": {
            "preferred_duration": "long (5+ years)",
            "preferred_coupon_type": "fixed",
            "avoid": ["floaters", "short-term (< 2 years)"],
            "strategy": "Покупать длинные ОФЗ и корпоративные облигации с фиксированным купоном. Цена будет расти при снижении ставки.",
            "target_sectors": ["ОФЗ", "AAA корпоративные"],
        },
        "hiking": {
            "preferred_duration": "short (< 2 years)",
            "preferred_coupon_type": "floating",
            "avoid": ["long-term (> 5 years) fixed"],
            "strategy": "Флоатеры, короткие облигации, депозиты. Длинные фиксированные облигации будут падать в цене.",
            "target_sectors": ["Флоатеры", "Краткосрочные ОФЗ"],
        },
        "stable": {
            "preferred_duration": "any",
            "preferred_coupon_type": "any",
            "avoid": [],
            "strategy": "Стандартная стратегия. Выбирать по YTM и кредитному качеству.",
            "target_sectors": ["Все"],
        },
    }
    return recommendations.get(rate_cycle, recommendations["stable"])
