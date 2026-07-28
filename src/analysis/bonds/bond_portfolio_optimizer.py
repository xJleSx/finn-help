from __future__ import annotations

from datetime import date
from typing import Any

from src.analysis.bonds.default_risk_analyzer import (
    _is_investment_grade,
    _is_speculative,
    analyze_default_impact,
)
from src.config import (
    BOND_PORTFOLIO_RULES,
    GOV_BOND_PREFIXES,
    QUASI_GOV_KEYWORDS,
)


def optimize_bond_portfolio(
    positions: list[dict[str, Any]],
    portfolio_value: float | None = None,
    rate_cycle_phase: str | None = None,
    is_small_portfolio: bool | None = None,
) -> dict[str, Any]:
    if not positions:
        return {
            "sellRecommendations": [],
            "buyRecommendations": [],
            "holdRecommendations": [],
            "summary": _empty_summary(),
        }

    total_value = portfolio_value or sum(p.get("totalValue", 0) or 0 for p in positions)
    is_small = is_small_portfolio if is_small_portfolio is not None else (total_value < BOND_PORTFOLIO_RULES["small_portfolio_threshold"])

    # Compute portfolio-level metrics
    rating_distribution: dict[str, float] = {}
    sector_allocation: dict[str, float] = {}
    maturity_dates: list[tuple[str, str, float]] = []
    total_gov_quasi_value = 0.0
    total_speculative_value = 0.0
    weighted_ytm_sum = 0.0
    weighted_duration_sum = 0.0
    weight_sum = 0.0

    for pos in positions:
        val = pos.get("totalValue", 0) or 0
        pct = (val / total_value * 100) if total_value > 0 else 0
        rating = pos.get("rating") or "NR"

        rating_distribution[rating] = rating_distribution.get(rating, 0) + pct

        ticker = pos.get("ticker", "")
        if _is_gov_or_quasi(ticker, pos.get("issuer", "")):
            total_gov_quasi_value += val
            label = "Гос/квази-гос"
        elif _is_speculative(rating):
            total_speculative_value += val
            label = "Спекулятивные"
        else:
            label = "Корпоративные"

        sector_allocation[label] = sector_allocation.get(label, 0) + pct

        maturity = pos.get("maturityDate")
        if maturity:
            maturity_dates.append((ticker, maturity, val))

        ytm = pos.get("ytm") or 0
        dur = pos.get("duration") or 0
        if ytm and ytm > 0:
            weighted_ytm_sum += ytm * val
            weighted_duration_sum += dur * val
            weight_sum += val

    gov_quasi_pct = (total_gov_quasi_value / total_value * 100) if total_value > 0 else 0
    speculative_pct = (total_speculative_value / total_value * 100) if total_value > 0 else 0
    avg_ytm = (weighted_ytm_sum / weight_sum) if weight_sum > 0 else 0
    avg_duration = (weighted_duration_sum / weight_sum) if weight_sum > 0 else 0

    # Default impact analysis
    default_impact = analyze_default_impact(positions, total_value, avg_ytm)

    sell_recs: list[dict[str, Any]] = []
    buy_recs: list[dict[str, Any]] = []
    hold_recs: list[dict[str, Any]] = []

    # --- SELL logic ---
    for pos in default_impact["positions"]:
        if pos["severity"] == "critical":
            sell_recs.append({
                "ticker": pos["ticker"],
                "reason": (
                    f"Критический риск дефолта: {pos['positionPct']}% портфеля в "
                    f"{pos['rating']}, восстановление {pos['monthsToRecover']} мес."
                ),
                "priority": "high",
                "action": "sell",
                "positionPct": pos["positionPct"],
            })
        elif pos["severity"] == "warning":
            sell_recs.append({
                "ticker": pos["ticker"],
                "reason": (
                    f"Повышенный риск: {pos['positionPct']}% портфеля в "
                    f"{pos['rating']}, неинвестиционный уровень"
                ),
                "priority": "medium",
                "action": "reduce",
                "positionPct": pos["positionPct"],
            })
        else:
            hold_recs.append({
                "ticker": pos["ticker"],
                "reason": f"Приемлемый риск: {pos['rating']}, {pos['positionPct']}% портфеля",
                "priority": "low",
                "action": "hold",
            })

    # --- Allocation-based SELL logic ---
    min_gov = BOND_PORTFOLIO_RULES["small_portfolio_min_gov_pct"] if is_small else BOND_PORTFOLIO_RULES["min_gov_quasi_pct"]
    if gov_quasi_pct < min_gov * 100:
        for pos in positions:
            rating = pos.get("rating") or "NR"
            if not _is_investment_grade(rating):
                existing = [s for s in sell_recs if s["ticker"] == pos.get("ticker")]
                if not existing:
                    sell_recs.append({
                        "ticker": pos.get("ticker", "?"),
                        "reason": (
                            f"Недостаточно гос/квази-гос ({gov_quasi_pct:.0f}% вместо "
                            f"{min_gov * 100:.0f}%) — сократить спекулятивные позиции"
                        ),
                        "priority": "medium",
                        "action": "reduce",
                        "positionPct": (pos.get("totalValue", 0) or 0) / total_value * 100 if total_value > 0 else 0,
                    })

    max_spec = BOND_PORTFOLIO_RULES["max_speculative_pct"]
    if speculative_pct > max_spec * 100:
        sell_recs.append({
            "ticker": "PORTFOLIO",
            "reason": (
                f"Превышение лимита спекулятивных позиций: {speculative_pct:.0f}% "
                f"при максимуме {max_spec * 100:.0f}%"
            ),
            "priority": "medium",
            "action": "reduce_speculative",
            "positionPct": speculative_pct,
        })

    # --- BUY logic ---
    if rate_cycle_phase == "cutting" and avg_duration < 4:
        buy_recs.append({
            "ticker": "длинные ОФЗ / AAA корпоративные",
            "reason": (
                f"Цикл снижения ставки: текущая дюрация {avg_duration:.1f}л ниже "
                f"оптимальной. Добавить длинные облигации с фиксированным купоном."
            ),
            "priority": "high",
            "action": "buy_long_fixed",
        })

    if is_small and gov_quasi_pct < 70:
        buy_recs.append({
            "ticker": "ОФЗ / квази-гос облигации",
            "reason": (
                f"Портфель < {BOND_PORTFOLIO_RULES['small_portfolio_threshold']}₽: "
                f"гос/квази-гос доля {gov_quasi_pct:.0f}% ниже рекомендуемых 70%"
            ),
            "priority": "high",
            "action": "buy_gov",
        })

    summary = {
        "totalValue": round(total_value, 2),
        "avgYtm": round(avg_ytm, 2),
        "avgDuration": round(avg_duration, 2),
        "govQuasiPct": round(gov_quasi_pct, 1),
        "speculativePct": round(speculative_pct, 1),
        "investmentGradePct": round(100 - speculative_pct, 1),
        "ratingDistribution": rating_distribution,
        "sectorAllocation": sector_allocation,
        "isSmallPortfolio": is_small,
        "portfolioValue": round(total_value, 2),
        "defaultRisk": default_impact["aggregate"],
        "maturityProfile": _build_maturity_profile(maturity_dates),
    }

    return {
        "sellRecommendations": sell_recs,
        "buyRecommendations": buy_recs,
        "holdRecommendations": hold_recs,
        "summary": summary,
    }


def _is_gov_or_quasi(ticker: str, issuer: str = "") -> bool:
    upper_ticker = ticker.upper()
    for prefix in GOV_BOND_PREFIXES:
        if upper_ticker.startswith(prefix):
            return True
    lower_issuer = issuer.lower()
    return any(kw in lower_issuer for kw in QUASI_GOV_KEYWORDS)


def _build_maturity_profile(maturity_dates: list[tuple[str, str, float]]) -> list[dict[str, Any]]:
    if not maturity_dates:
        return []
    by_year: dict[int, list[dict[str, Any]]] = {}
    for ticker, mat_str, val in maturity_dates:
        try:
            yr = date.fromisoformat(mat_str).year
        except (ValueError, TypeError):
            continue
        if yr not in by_year:
            by_year[yr] = []
        by_year[yr].append({"ticker": ticker, "value": round(val, 2)})

    profile = []
    for year in sorted(by_year.keys()):
        bonds = by_year[year]
        total = sum(b["value"] for b in bonds)
        profile.append({"year": year, "bonds": bonds, "totalValue": round(total, 2)})
    return profile


def _empty_summary() -> dict[str, Any]:
    return {
        "totalValue": 0,
        "avgYtm": 0,
        "avgDuration": 0,
        "govQuasiPct": 0,
        "speculativePct": 0,
        "investmentGradePct": 0,
        "ratingDistribution": {},
        "sectorAllocation": {},
        "isSmallPortfolio": False,
        "portfolioValue": 0,
        "defaultRisk": {},
        "maturityProfile": [],
    }
