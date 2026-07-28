from __future__ import annotations

from typing import Any

CREDIT_RATING_ORDER: dict[str, int] = {
    "AAA": 0, "AA+": 1, "AA": 2, "AA-": 3,
    "A+": 4, "A": 5, "A-": 6,
    "BBB+": 7, "BBB": 8, "BBB-": 9,
    "BB+": 10, "BB": 11, "B+": 12, "B": 13,
    "B-": 14, "CCC+": 15, "CCC": 16, "CCC-": 17,
    "CC": 18, "C": 19, "D": 20,
}

SPECULATIVE_THRESHOLD = CREDIT_RATING_ORDER.get("BB+", 10)
DEFAULT_RISK_THRESHOLD = CREDIT_RATING_ORDER.get("CCC+", 15)


def _rating_to_score(rating: str | None) -> int:
    if not rating:
        return 99
    return CREDIT_RATING_ORDER.get(rating.upper().strip(), 99)


def _is_investment_grade(rating: str | None) -> bool:
    return _rating_to_score(rating) <= CREDIT_RATING_ORDER.get("BBB-", 9)


def _is_speculative(rating: str | None) -> bool:
    score = _rating_to_score(rating)
    return SPECULATIVE_THRESHOLD <= score < DEFAULT_RISK_THRESHOLD


def analyze_default_impact(
    positions: list[dict[str, Any]],
    portfolio_value: float | None = None,
    portfolio_avg_ytm: float | None = None,
) -> dict[str, Any]:
    if not positions:
        return {"positions": [], "aggregate": _empty_aggregate()}

    total_value = portfolio_value or sum(p.get("totalValue", 0) or 0 for p in positions)
    sum(p.get("totalInvested", 0) or 0 for p in positions)

    weighted_ytm_sum = 0.0
    weighted_ytm_weight = 0.0
    ytms = []

    for p in positions:
        ytm = p.get("ytm") or p.get("yieldToMaturity") or 0
        if ytm and ytm > 0:
            val = p.get("totalValue", 0) or 1
            weighted_ytm_sum += ytm * val
            weighted_ytm_weight += val
            ytms.append(ytm)

    avg_ytm = portfolio_avg_ytm or (weighted_ytm_sum / weighted_ytm_weight if weighted_ytm_weight > 0 else 0)

    position_results = []
    total_default_loss = 0.0
    critical_count = 0
    warning_count = 0

    for pos in positions:
        ticker = pos.get("ticker", "?")
        rating = pos.get("rating") or "NR"
        pos_value = pos.get("totalValue", 0) or 0
        pos_pct = (pos_value / total_value * 100) if total_value > 0 else 0

        required_return_pct = (pos_value / total_value * 100) if total_value > 0 else 0
        months_to_recover = (required_return_pct / (avg_ytm / 12)) if avg_ytm > 0 else float("inf")

        rating_score = _rating_to_score(rating)
        is_spec = _is_speculative(rating)
        is_default_risk = rating_score >= DEFAULT_RISK_THRESHOLD
        is_inv_grade = _is_investment_grade(rating)

        severity = "low"
        if is_default_risk or (is_spec and pos_pct > 10):
            severity = "critical"
        elif is_spec and pos_pct > 5:
            severity = "warning"
        elif not is_inv_grade and pos_pct > 15:
            severity = "critical"
        elif not is_inv_grade:
            severity = "warning"

        if severity == "critical":
            critical_count += 1
        elif severity == "warning":
            warning_count += 1

        total_default_loss += pos_value
        pos["aiScore"] = 50

        position_results.append({
            "ticker": ticker,
            "rating": rating,
            "positionValue": round(pos_value, 2),
            "positionPct": round(pos_pct, 2),
            "lossIfDefault": round(pos_value, 2),
            "requiredReturnPct": round(required_return_pct, 2),
            "monthsToRecover": round(months_to_recover, 1) if months_to_recover != float("inf") else None,
            "isInvestmentGrade": is_inv_grade,
            "isSpeculative": is_spec,
            "severity": severity,
        })

    recovery_months = (total_default_loss / total_value * 100 / (avg_ytm / 12)) if total_value > 0 and avg_ytm > 0 else None

    aggregate = {
        "totalValue": round(total_value, 2),
        "totalDefaultLossIfAllDefault": round(total_default_loss, 2),
        "portfolioDefaultLossPct": round(total_default_loss / total_value * 100, 2) if total_value > 0 else 0,
        "monthsToRecoverFromTotalDefault": round(recovery_months, 1) if recovery_months else None,
        "avgYtm": round(avg_ytm, 2),
        "criticalPositions": critical_count,
        "warningPositions": warning_count,
        "safePositions": len(positions) - critical_count - warning_count,
        "speculativeExposurePct": round(
            sum(
                p["positionPct"] for p in position_results if p["isSpeculative"]
            ), 2
        ),
    }

    return {
        "positions": position_results,
        "aggregate": aggregate,
    }


def _empty_aggregate() -> dict[str, Any]:
    return {
        "totalValue": 0,
        "totalDefaultLossIfAllDefault": 0,
        "portfolioDefaultLossPct": 0,
        "monthsToRecoverFromTotalDefault": None,
        "avgYtm": 0,
        "criticalPositions": 0,
        "warningPositions": 0,
        "safePositions": 0,
        "speculativeExposurePct": 0,
    }


def get_default_impact_for_position(
    position_value: float,
    portfolio_value: float,
    rating: str | None,
    ytm: float | None = None,
    portfolio_avg_ytm: float | None = None,
) -> dict[str, Any]:
    pos_pct = (position_value / portfolio_value * 100) if portfolio_value > 0 else 0
    avg_ytm = portfolio_avg_ytm or ytm or 15.0
    months_to_recover = (pos_pct / (avg_ytm / 12)) if avg_ytm > 0 else float("inf")

    rating_score = _rating_to_score(rating)
    is_inv_grade = _is_investment_grade(rating)
    is_spec = _is_speculative(rating)

    severity = "low"
    if rating_score >= DEFAULT_RISK_THRESHOLD or (is_spec and pos_pct > 10):
        severity = "critical"
    elif is_spec and pos_pct > 5 or not is_inv_grade:
        severity = "warning"

    return {
        "positionPct": round(pos_pct, 2),
        "lossIfDefault": round(position_value, 2),
        "requiredReturnPct": round(pos_pct, 2),
        "monthsToRecover": round(months_to_recover, 1) if months_to_recover != float("inf") else None,
        "isInvestmentGrade": is_inv_grade,
        "isSpeculative": is_spec,
        "severity": severity,
    }
