"""Portfolio bonds endpoints — positions, summary, allocation, cash-flow."""

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.analysis.bonds.bond_portfolio_optimizer import optimize_bond_portfolio
from src.analysis.bonds.default_risk_analyzer import analyze_default_impact
from src.analysis.bonds.rate_cycle import detect_rate_cycle, get_rate_cycle_recommendation
from src.db.models import Instrument, Portfolio, Price, User
from src.interfaces.api.auth import require_user
from src.interfaces.api.dependencies import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["portfolio-bonds"], prefix="/api/portfolio")


@router.get("/bonds")
async def get_portfolio_bonds(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    user_id = user.id

    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.instrument).selectinload(Instrument.bond_offerings))
        .where(Portfolio.user_id == user_id)
    )
    positions = result.scalars().all()

    items: list[dict[str, Any]] = []
    total_value = 0.0
    total_invested = 0.0

    for pos in positions:
        inst = pos.instrument
        if not inst or inst.instrument_type != "bond":
            continue

        offering = None
        if inst.bond_offerings:
            offering = sorted(inst.bond_offerings, key=lambda o: o.offering_date or date.min, reverse=True)[0]

        price_result = await db.execute(
            select(Price).where(Price.instrument_id == inst.id).order_by(Price.date.desc()).limit(1)
        )
        last_price_row = price_result.scalar_one_or_none()
        current_price = float(last_price_row.close) if last_price_row and last_price_row.close else 0

        if current_price == 0 and offering and offering.nominal_price:
            pct = offering.current_price_pct or 100.0
            current_price = offering.nominal_price * pct / 100.0

        qty = float(pos.quantity)
        avg_price = float(pos.avg_price or 0)
        pos_value = current_price * qty
        pos_invested = avg_price * qty if avg_price > 0 else pos_value
        profit = pos_value - pos_invested
        profit_pct = (profit / pos_invested * 100) if pos_invested > 0 else 0

        total_value += pos_value
        total_invested += pos_invested

        items.append({
            "id": str(inst.id),
            "ticker": inst.ticker,
            "isin": offering.isin if offering else (inst.isin or ""),
            "name": inst.full_name or inst.ticker,
            "issuer": inst.full_name or "",
            "quantity": qty,
            "avgPrice": round(avg_price, 2),
            "currentPrice": round(current_price, 2),
            "totalValue": round(pos_value, 2),
            "totalInvested": round(pos_invested, 2),
            "profit": round(profit, 2),
            "profitPercent": round(profit_pct, 2),
            "ytm": round(offering.yield_to_maturity, 2) if offering and offering.yield_to_maturity else 0,
            "couponYield": round(offering.coupon_rate, 2) if offering and offering.coupon_rate else 0,
            "duration": round(offering.duration_years, 2) if offering and offering.duration_years else 0,
            "rating": (offering.credit_rating or "NR") if offering else "NR",
            "maturityDate": offering.maturity_date.isoformat() if offering and offering.maturity_date else "",
            "aiScore": 50,
            "allocation": 0.0,
        })

    total_profit = total_value - total_invested
    total_return = (total_profit / total_invested * 100) if total_invested > 0 else 0

    ytms = [i["ytm"] for i in items if i["ytm"] > 0]
    avg_ytm = round(sum(ytms) / len(ytms), 2) if ytms else 0

    summary = {
        "totalValue": round(total_value, 2),
        "totalProfit": round(total_profit, 2),
        "totalReturn": round(total_return, 2),
        "avgYtm": avg_ytm,
        "avgAiScore": 50,
    }

    sorted_by_value = sorted(items, key=lambda x: x["totalValue"], reverse=True)
    for i in sorted_by_value:
        if total_value > 0:
            i["allocation"] = round(i["totalValue"] / total_value * 100, 1)

    allocation = {
        "recommended": [
            {"label": "ОФЗ", "value": 30},
            {"label": "Корпоративные AAA", "value": 25},
            {"label": "Корпоративные A", "value": 25},
            {"label": "Высокодоходные", "value": 10},
            {"label": "Кэш", "value": 10},
        ],
        "actual": [
            {"label": "ОФЗ", "value": 0},
            {"label": "Корпоративные AAA", "value": 0},
            {"label": "Корпоративные A", "value": 0},
            {"label": "Высокодоходные", "value": 0},
            {"label": "Кэш", "value": 0},
        ],
    }

    for i in sorted_by_value:
        label = "ОФЗ" if i["ticker"].startswith("SU") else "Корпоративные AAA" if i["rating"].startswith("A") else "Корпоративные A" if i["rating"].startswith("BBB") else "Высокодоходные"
        for a in allocation["actual"]:
            if a["label"] == label:
                a["value"] = round(a["value"] + (i.get("allocation", 0) or 0), 1)

    # ── Extended analytics ────────────────────────────────────────────────

    default_impact = analyze_default_impact(items, total_value, avg_ytm)

    rate_cycle = detect_rate_cycle()
    rate_cycle_rec = get_rate_cycle_recommendation(rate_cycle.get("phase", "stable"))

    portfolio_optimization = optimize_bond_portfolio(
        items,
        portfolio_value=total_value,
        rate_cycle_phase=rate_cycle.get("phase"),
    )

    # ── Scenario B ────────────────────────────────────────────────────────
    from src.analysis.bonds.inflation_fetcher import get_inflation_forecast
    from src.analysis.bonds.macro_scenario_engine import select_scenario
    from src.analysis.bonds.rate_cycle_scenario_b import scenario_b_plan
    from src.analysis.bonds.rebalancing_triggers import check_triggers

    durations = [i.get("duration", 0) or 0 for i in items if i.get("duration")]
    avg_dur = sum(durations) / len(durations) if durations else 0

    inflation = get_inflation_forecast()

    scenario_b = scenario_b_plan(
        positions=items,
        portfolio_value=total_value,
        current_duration=avg_dur,
        rate_unchanged_months=4,
        inflation_pct=inflation.get("inflationForecast", 6.5) * 100,
        deposit_rate=15.0,
    )

    # ── Rebalancing triggers ──────────────────────────────────────────────
    rebalance = check_triggers(
        positions=items,
        portfolio_value=total_value,
    )

    # ── Macro scenario ──────────────────────────────────────────────────
    macro = select_scenario(
        key_rate=(rate_cycle.get("keyRate") if isinstance(rate_cycle.get("keyRate"), (int, float)) else 0.16),
        inflation=inflation.get("inflationForecast", 0.065),
        ruonia=0.15,
        gdp_growth=0.01,
    )

    # Health score (0-100)
    health_score = _compute_health_score(
        items,
        default_impact,
        rate_cycle.get("phase", "stable"),
        total_value,
    )

    # Warnings
    warnings = _build_warnings(default_impact, portfolio_optimization, rate_cycle, scenario_b, rebalance)

    # Rating distribution
    rating_dist: dict[str, float] = {}
    for i in items:
        r = i.get("rating", "NR")
        a = i.get("allocation", 0) or 0
        rating_dist[r] = rating_dist.get(r, 0) + a

    # Ladder
    ladder: list[dict[str, Any]] = []
    for i in items:
        mat = i.get("maturityDate", "")
        if mat:
            try:
                yr = date.fromisoformat(mat).year
            except (ValueError, TypeError):
                continue
            ladder.append({
                "year": yr,
                "ticker": i["ticker"],
                "value": i["totalValue"],
                "ytm": i["ytm"],
                "rating": i["rating"],
            })
    ladder.sort(key=lambda x: (x["year"], x["ticker"]))

    return {
        "positions": sorted_by_value,
        "summary": summary,
        "allocation": allocation,
        "defaultImpact": {
            "positions": default_impact["positions"],
            "aggregate": default_impact["aggregate"],
        },
        "rateCycle": {
            "phase": rate_cycle.get("phase"),
            "direction": rate_cycle.get("direction"),
            "label": rate_cycle.get("label"),
            "description": rate_cycle.get("description"),
            "confidence": rate_cycle.get("confidence"),
            "ruoniaSpreadBps": rate_cycle.get("ruoniaSpreadBps"),
            "ofzShortYield": rate_cycle.get("ofzShortYield"),
            "cbrRhetoric": rate_cycle.get("cbrRhetoric"),
            "recommendation": rate_cycle_rec,
        },
        "scenarioB": scenario_b,
        "rebalancing": rebalance,
        "macroScenario": macro,
        "inflationForecast": inflation,
        "ladder": ladder,
        "healthScore": health_score,
        "warnings": warnings,
        "ratingDistribution": rating_dist,
        "portfolioOptimization": portfolio_optimization,
    }


def _compute_health_score(
    items: list[dict[str, Any]],
    default_impact: dict[str, Any],
    rate_cycle_phase: str,
    total_value: float,
) -> int:
    score = 70  # start at 70

    agg = default_impact.get("aggregate", {})
    if agg.get("criticalPositions", 0) > 0:
        score -= 20 * min(agg["criticalPositions"], 3)
    if agg.get("warningPositions", 0) > 0:
        score -= 10 * min(agg["warningPositions"], 3)
    spec_pct = agg.get("speculativeExposurePct", 0)
    if spec_pct > 20:
        score -= 15
    elif spec_pct > 10:
        score -= 5

    durations = [i.get("duration", 0) or 0 for i in items if i.get("duration")]
    if durations:
        avg_dur = sum(durations) / len(durations)
        if rate_cycle_phase == "cutting" and avg_dur < 3:
            score -= 10  # too short for cutting cycle
        elif rate_cycle_phase == "hiking" and avg_dur > 5:
            score -= 15  # too long for hiking cycle

    ratings = [i.get("rating", "NR") for i in items]
    non_rated = sum(1 for r in ratings if r == "NR")
    if non_rated > 0:
        score -= 5 * non_rated

    return max(0, min(100, score))


def _build_warnings(
    default_impact: dict[str, Any],
    portfolio_optimization: dict[str, Any],
    rate_cycle: dict[str, Any],
    scenario_b_data: dict[str, Any] | None = None,
    rebalance_data: dict[str, Any] | None = None,
) -> list[str]:
    warnings: list[str] = []

    agg = default_impact.get("aggregate", {})
    if agg.get("criticalPositions", 0) > 0:
        for pos in default_impact.get("positions", []):
            if pos.get("severity") == "critical":
                warnings.append(
                    f"{pos.get('ticker', '?')}: {pos.get('positionPct', 0)}% портфеля "
                    f"с рейтингом {pos.get('rating', 'NR')} — критический риск дефолта"
                )

    if agg.get("speculativeExposurePct", 0) > 10:
        warnings.append(
            f"Спекулятивные позиции: {agg['speculativeExposurePct']}% портфеля "
            f"(рекомендуется не более 10%)"
        )

    sells = portfolio_optimization.get("sellRecommendations", [])
    for s in sells[:3]:
        warnings.append(s.get("reason", ""))

    if scenario_b_data and scenario_b_data.get("scenarioBActive"):
        warnings.append("Сценарий B активен: заменить длинные позиции на короткие ОФЗ/флоатеры")

    if rebalance_data:
        high_triggers = rebalance_data.get("severityCount", {}).get("high", 0)
        if high_triggers > 0:
            warnings.append(f"{high_triggers} высокоприоритетных триггера ребалансировки активны")

    return warnings[:8]
