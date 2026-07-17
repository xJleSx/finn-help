from __future__ import annotations

from typing import Any, Optional

CREDIT_RATING_ORDER: dict[str, int] = {
    "AAA": 0, "AA+": 1, "AA": 2, "AA-": 3,
    "A+": 4, "A": 5, "A-": 6,
    "BBB+": 7, "BBB": 8, "BBB-": 9,
    "BB+": 10, "BB": 11, "B+": 12, "B": 13,
}


def analyze_bond(
    bond_offering: Optional[dict[str, Any]] = None,
    key_rate: Optional[float] = None,
    ofz_yield: Optional[float] = None,
) -> dict[str, Any]:
    if not bond_offering:
        return {"score": 0.0, "action": "NEUTRAL", "reasons": ["Нет данных об облигации"], "risk": 0.5}

    score = 0.0
    reasons: list[str] = []
    risk_score = 0.0

    ytm = bond_offering.get("yield_to_maturity")
    coupon_rate = bond_offering.get("coupon_rate")
    credit_rating = bond_offering.get("credit_rating")
    duration = bond_offering.get("duration_years")
    coupon_type = bond_offering.get("coupon_type", "fixed")
    has_amortization = bond_offering.get("has_amortization", False)
    has_offer = bond_offering.get("has_offer", False)

    # YTM evaluation
    if ytm is not None:
        if key_rate is not None:
            spread = ytm - key_rate
            if spread > 3:
                score += 0.25
                reasons.append(f"Спред к ключевой ставке {spread:+.1f}% — привлекательно")
            elif spread > 0:
                score += 0.1
                reasons.append(f"YTM ({ytm:.1f}%) выше ключевой ставки ({key_rate:.1f}%)")
            else:
                score -= 0.15
                reasons.append(f"YTM ({ytm:.1f}%) ниже ключевой ставки ({key_rate:.1f}%)")
                risk_score += 0.15

        if ofz_yield is not None:
            ofz_spread = ytm - ofz_yield
            if ofz_spread > 2:
                score -= 0.1
                risk_score += 0.1
                reasons.append(f"Спред к ОФЗ {ofz_spread:+.1f}% — повышенный риск")
            elif ofz_spread > 0:
                score += 0.1
                reasons.append(f"Премия к ОФЗ {ofz_spread:+.1f}%")
            else:
                score += 0.15
                reasons.append("Доходность ниже ОФЗ — качественная облигация")

        if ytm > 20:
            score -= 0.2
            risk_score += 0.2
            reasons.append("Чрезмерно высокая доходность — высокий риск дефолта")
        elif ytm > 15:
            score += 0.05
            reasons.append("Высокая доходность")
        elif ytm > 5:
            score -= 0.05
        elif ytm > 0:
            score -= 0.1
            reasons.append("Низкая доходность")

    # Credit rating evaluation
    if credit_rating:
        rating_upper = credit_rating.upper()
        rating_pos = CREDIT_RATING_ORDER.get(rating_upper, 99)
        if rating_pos <= 3:
            score += 0.2
            reasons.append(f"Высокий кредитный рейтинг: {credit_rating}")
        elif rating_pos <= 6:
            score += 0.1
            reasons.append(f"Хороший кредитный рейтинг: {credit_rating}")
        elif rating_pos <= 9:
            score += 0.0
            risk_score += 0.15
            reasons.append(f"Средний кредитный рейтинг: {credit_rating}")
        else:
            score -= 0.2
            risk_score += 0.3
            reasons.append(f"Низкий кредитный рейтинг: {credit_rating}")
    else:
        risk_score += 0.1
        reasons.append("Нет данных о кредитном рейтинге")

    # Duration evaluation
    if duration is not None:
        if duration > 7:
            score -= 0.15
            risk_score += 0.2
            reasons.append(f"Большая дюрация ({duration:.1f}л) — высокий процентный риск")
        elif duration > 3:
            score -= 0.05
            risk_score += 0.05
            reasons.append(f"Умеренная дюрация ({duration:.1f}л)")
        elif duration > 0:
            score += 0.1
            reasons.append(f"Короткая дюрация ({duration:.1f}л) — низкий процентный риск")

    # Coupon type
    if coupon_type:
        ct = coupon_type.lower()
        if ct in ("float", "floating", "floater"):
            score += 0.1
            reasons.append("Плавающий купон — защита от роста ставок")
        elif ct in ("zero", "zero-coupon", "discount"):
            score -= 0.05
            risk_score += 0.05
            reasons.append("Бескупонная (дисконтная) облигация")

    # Features
    if has_amortization:
        score += 0.05
        reasons.append("Амортизация — частичное досрочное погашение")
        risk_score -= 0.05

    if has_offer:
        score += 0.05
        reasons.append("Оферта — возможность досрочного предъявления к выкупу")

    # Normalize score
    score = max(-1.0, min(1.0, score))

    # Determine action
    if score > 0.25:
        action = "BUY"
    elif score > 0.05:
        action = "CAUTIOUS_BUY"
    elif score < -0.15:
        action = "SELL"
    else:
        action = "HOLD"

    risk_score = max(0.0, min(1.0, risk_score))

    return {
        "score": round(score, 3),
        "action": action,
        "reasons": reasons[:6],
        "risk": round(risk_score, 2),
    }
