from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.analysis.portfolio.black_litterman import BlackLittermanAllocator, MarketView
from src.db.models import BondOffering, Instrument, Portfolio, Price, Signal
from src.notifications import RebalanceAlert

logger = logging.getLogger(__name__)

DEFAULT_COMMISSION_RATE = 0.0005
DEFAULT_SLIPPAGE_RATE = 0.001
TAX_RATE_LONG_TERM = 0.13
TAX_RATE_SHORT_TERM = 0.13
HOLDING_PERIOD_DAYS_LONG_TERM = 365


@dataclass
class RebalanceAction:
    ticker: str
    current_weight: float
    target_weight: float
    deviation: float
    action: str
    quantity: int
    estimated_cost: float
    reason: str


@dataclass
class RebalancePlan:
    actions: list[RebalanceAction]
    total_trades: int
    estimated_commission: float
    turnover: float
    portfolio_value: float
    sector_breaks: list[dict]


class RebalancingEngine:
    def __init__(
        self,
        max_sector_pct: float = 0.35,
        max_position_pct: float = 0.15,
        rebalance_threshold: float = 0.05,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
    ) -> None:
        self.max_sector_pct = max_sector_pct
        self.max_position_pct = max_position_pct
        self.rebalance_threshold = rebalance_threshold
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

    def analyze_portfolio(
        self,
        db: Any,
        user_id: int = 0,
        target_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Synchronous portfolio analysis. Use async_analyze_portfolio in async contexts."""
        positions = db.query(Portfolio).filter_by(user_id=user_id).all()
        if not positions:
            return []

        portfolio_items: list[dict[str, Any]] = []
        total_value = 0.0

        inst_ids = list({pos.instrument_id for pos in positions if pos.instrument_id})
        inst_map: dict[int, Any] = {}
        if inst_ids:
            for row in db.query(Instrument).filter(Instrument.id.in_(inst_ids)).all():
                inst_map[row.id] = row

            price_map: dict[int, Any] = {}
            for row in (
                db.query(Price)
                .distinct(Price.instrument_id)
                .filter(Price.instrument_id.in_(inst_ids))
                .order_by(Price.instrument_id, Price.date.desc())
                .all()
            ):
                price_map[row.instrument_id] = row

        for pos in positions:
            if not pos.instrument_id:
                continue
            instr = inst_map.get(pos.instrument_id)
            if not instr:
                continue
            price_row = price_map.get(pos.instrument_id)
            if not price_row or not price_row.close:
                continue
            current_price = float(price_row.close)
            value = current_price * float(pos.quantity)
            total_value += value
            portfolio_items.append(
                {
                    "ticker": instr.ticker,
                    "sector": instr.sector or "Прочее",
                    "quantity": float(pos.quantity),
                    "current_price": current_price,
                    "value": value,
                    "instrument_id": instr.id,
                }
            )

        if total_value <= 0:
            return []

        for item in portfolio_items:
            item["weight"] = item["value"] / total_value

        if target_weights:
            total_weight = sum(target_weights.values())
            if total_weight > 0:
                target_weights = {k: v / total_weight for k, v in target_weights.items()}
        else:
            n = len(portfolio_items)
            if n > 0:
                equal_weight = 1.0 / n
                target_weights = {item["ticker"]: equal_weight for item in portfolio_items}

        sector_map: dict[str, float] = {}
        for item in portfolio_items:
            sector = item["sector"]
            sector_map[sector] = sector_map.get(sector, 0.0) + item["weight"]

        results: list[dict[str, Any]] = []
        for item in portfolio_items:
            ticker = item["ticker"]
            current_weight = item["weight"]
            target_weight = target_weights.get(ticker, 0.0)
            deviation = current_weight - target_weight
            alerts: list[str] = []

            if deviation > self.rebalance_threshold:
                alerts.append("overweight")
            elif deviation < -self.rebalance_threshold:
                alerts.append("underweight")

            if item["weight"] > self.max_position_pct:
                alerts.append("position_exceeds_limit")

            results.append(
                {
                    "ticker": ticker,
                    "sector": item["sector"],
                    "current_weight": round(current_weight, 4),
                    "target_weight": round(target_weight, 4),
                    "deviation": round(deviation, 4),
                    "current_price": item["current_price"],
                    "quantity": int(item["quantity"]),
                    "value": round(item["value"], 2),
                    "alerts": alerts,
                }
            )

        return results

    def generate_plan(
        self,
        db: Any,
        user_id: int = 0,
        target_weights: dict[str, float] | None = None,
    ) -> RebalancePlan:
        analysis = self.analyze_portfolio(db, user_id, target_weights)
        if not analysis:
            return RebalancePlan(
                actions=[],
                total_trades=0,
                estimated_commission=0.0,
                turnover=0.0,
                portfolio_value=0.0,
                sector_breaks=[],
            )

        portfolio_value = sum(a["value"] for a in analysis)

        tickers = list({a["ticker"] for a in analysis})
        instr_rows = db.query(Instrument).filter(Instrument.ticker.in_(tickers)).all()
        instr_map: dict[str, Any] = {str(r.ticker): r for r in instr_rows}
        inst_id_to_ticker: dict[int, str] = {r.id: str(r.ticker) for r in instr_rows if r.ticker}
        inst_ids = list(inst_id_to_ticker)

        sig_map: dict[str, dict[str, Any]] = {}
        if inst_ids:
            seen_inst_ids: set[int] = set()
            for sig in (
                db.query(Signal)
                .filter(Signal.instrument_id.in_(inst_ids))
                .order_by(Signal.instrument_id, Signal.date.desc())
                .all()
            ):
                if sig.instrument_id not in seen_inst_ids:
                    seen_inst_ids.add(sig.instrument_id)
                    t = inst_id_to_ticker.get(sig.instrument_id)
                    if t:
                        sig_map[t] = {
                            "action": sig.action,
                            "confidence": sig.confidence or 0.0,
                        }

        actions: list[RebalanceAction] = []
        total_turnover = 0.0
        alerts: list[RebalanceAlert] = []

        for item in analysis:
            ticker = item["ticker"]
            deviation = item["deviation"]
            current_weight = item["current_weight"]
            target_weight = item["target_weight"]
            price = item["current_price"]
            quantity = item["quantity"]

            signal_info = sig_map.get(ticker, {})
            signal_action = signal_info.get("action", "HOLD")
            confidence = signal_info.get("confidence", 0.0)

            abs_dev = abs(deviation)

            if abs_dev < self.rebalance_threshold:
                actions.append(
                    RebalanceAction(
                        ticker=ticker,
                        current_weight=current_weight,
                        target_weight=target_weight,
                        deviation=deviation,
                        action="HOLD",
                        quantity=0,
                        estimated_cost=0.0,
                        reason="within threshold",
                    )
                )
                continue

            instr = instr_map.get(ticker)
            lot_size = 1
            if instr and instr.lot_size and instr.lot_size > 1:
                lot_size = instr.lot_size

            if deviation > 0:
                sell_value = deviation * portfolio_value
                sell_quantity = int(sell_value / price / lot_size) * lot_size if price > 0 else 0
                sell_quantity = min(sell_quantity, quantity)

                if sell_quantity > 0:
                    reason_parts = ["overweight"]
                    if confidence > 0.6 and signal_action == "SELL":
                        reason_parts.append(f"signal {signal_action}@{confidence}")
                    elif confidence > 0.6 and signal_action == "BUY":
                        sell_quantity = max(0, sell_quantity // 2)
                        reason_parts.append(f"partial (signal {signal_action})")

                    cost = sell_quantity * price
                    actions.append(
                        RebalanceAction(
                            ticker=ticker,
                            current_weight=current_weight,
                            target_weight=target_weight,
                            deviation=deviation,
                            action="SELL",
                            quantity=sell_quantity,
                            estimated_cost=round(cost, 2),
                            reason="; ".join(reason_parts),
                        )
                    )
                    total_turnover += cost
                    alerts.append(
                        RebalanceAlert(
                            ticker=ticker,
                            current_pct=current_weight,
                            target_pct=target_weight,
                            deviation_pct=deviation,
                            reason="; ".join(reason_parts),
                        )
                    )
            else:
                buy_value = abs(deviation) * portfolio_value
                buy_quantity = int(buy_value / price / lot_size) * lot_size if price > 0 else 0

                if buy_quantity > 0:
                    reason_parts = ["underweight"]
                    if confidence > 0.6 and signal_action == "BUY":
                        reason_parts.append(f"signal {signal_action}@{confidence}")
                    elif confidence > 0.6 and signal_action == "SELL":
                        buy_quantity = max(0, buy_quantity // 2)
                        reason_parts.append(f"partial (signal {signal_action})")

                    cost = buy_quantity * price
                    actions.append(
                        RebalanceAction(
                            ticker=ticker,
                            current_weight=current_weight,
                            target_weight=target_weight,
                            deviation=deviation,
                            action="BUY",
                            quantity=buy_quantity,
                            estimated_cost=round(cost, 2),
                            reason="; ".join(reason_parts),
                        )
                    )
                    total_turnover += cost
                    alerts.append(
                        RebalanceAlert(
                            ticker=ticker,
                            current_pct=current_weight,
                            target_pct=target_weight,
                            deviation_pct=deviation,
                            reason="; ".join(reason_parts),
                        )
                    )

        sector_breaks = self._check_sector_limits(analysis)

        estimated_commission = round(total_turnover * self.commission_rate, 2)
        round(total_turnover * self.slippage_rate, 2)

        tax_rate = TAX_RATE_LONG_TERM
        round(total_turnover * tax_rate * 0.3, 2)

        for a in actions:
            a.estimated_cost += round(a.estimated_cost * (self.commission_rate + self.slippage_rate), 2)

        if alerts:
            logger.info("Generated %d rebalance alerts", len(alerts))
        if self.commission_rate == 0 and total_turnover > 0:
            logger.info("Commission rate is 0, turnover=%.2f", total_turnover)

        return RebalancePlan(
            actions=actions,
            total_trades=len([a for a in actions if a.action != "HOLD"]),
            estimated_commission=estimated_commission,
            turnover=round(total_turnover, 2),
            portfolio_value=round(portfolio_value, 2),
            sector_breaks=sector_breaks,
        )

    def _check_sector_limits(
        self,
        analysis: list[dict[str, Any]],
    ) -> list[dict]:
        sector_map: dict[str, float] = {}
        for item in analysis:
            sector = item["sector"]
            sector_map[sector] = sector_map.get(sector, 0.0) + item["current_weight"]
        breaks: list[dict] = []
        for sector, weight in sector_map.items():
            if weight > self.max_sector_pct:
                breaks.append(
                    {
                        "sector": sector,
                        "weight": round(weight, 4),
                        "max_pct": self.max_sector_pct,
                        "excess": round(weight - self.max_sector_pct, 4),
                    }
                )
        return breaks

    def execute_plan(
        self,
        plan: RebalancePlan,
        broker: Any | None = None,
        dry_run: bool = True,
    ) -> list[dict[str, Any]]:
        trades: list[dict[str, Any]] = []
        for action in plan.actions:
            if action.action == "HOLD" or action.quantity == 0:
                continue

            trade: dict[str, Any] = {
                "ticker": action.ticker,
                "direction": action.action,
                "quantity": action.quantity,
                "estimated_cost": action.estimated_cost,
                "reason": action.reason,
                "status": "dry_run" if dry_run else "pending",
            }

            if broker and not dry_run:
                try:
                    order = broker.place_market_order(
                        ticker=action.ticker,
                        quantity=action.quantity,
                        direction=action.action.lower(),
                    )
                    trade["order_id"] = order.get("order_id") or ""
                    trade["executed_price"] = order.get("executed_price") or 0.0
                    trade["commission"] = order.get("commission") or 0.0
                    trade["status"] = "submitted"
                except Exception as e:
                    logger.error("Failed to execute %s %s: %s", action.action, action.ticker, e)
                    trade["status"] = "failed"
                    trade["error"] = str(e)

            trades.append(trade)

        return trades

    def black_litterman_rebalance(
        self,
        db: Any,
        user_id: int = 0,
        views: list[MarketView] | None = None,
        optimizer_method: str = "max_sharpe",
        tau: float = 0.05,
    ) -> RebalancePlan:
        positions = db.query(Portfolio).filter_by(user_id=user_id).all()
        if not positions or not views:
            return self.generate_plan(db, user_id)

        inst_ids = list({pos.instrument_id for pos in positions if pos.instrument_id})
        instr_rows = db.query(Instrument).filter(Instrument.id.in_(inst_ids)).all() if inst_ids else []
        tickers = [str(r.ticker) for r in instr_rows]
        if not tickers:
            return self.generate_plan(db, user_id)

        price_rows = (
            db.query(Price)
            .filter(Price.instrument_id.in_(inst_ids))
            .order_by(Price.instrument_id, Price.date.desc())
            .all()
        )
        price_map: dict[int, float] = {}
        for r in price_rows:
            if r.instrument_id not in price_map and r.close:
                price_map[r.instrument_id] = float(r.close)

        total_value = 0.0
        pos_values: dict[str, float] = {}
        instr_map = {r.id: str(r.ticker) for r in instr_rows}
        for pos in positions:
            if not pos.instrument_id:
                continue
            ticker = instr_map.get(pos.instrument_id)
            price = price_map.get(pos.instrument_id, 0)
            if not ticker or price <= 0:
                continue
            val = price * float(pos.quantity)
            pos_values[ticker] = val
            total_value += val

        if total_value <= 0:
            return self.generate_plan(db, user_id)

        market_weights = {t: v / total_value for t, v in pos_values.items()}
        n = len(tickers)
        cov = np.eye(n) * 0.04
        np.fill_diagonal(cov, 0.04)
        cov_df = pd.DataFrame(cov, index=tickers, columns=tickers)

        allocator = BlackLittermanAllocator(market_weights, cov_df, tau=tau)
        result = allocator.allocate(views, optimizer_method=optimizer_method)
        raw_weights = result["weights"]
        target_weights = {k: max(v, 0.0) for k, v in raw_weights.items()}
        tw_sum = sum(target_weights.values())
        if tw_sum > 0:
            target_weights = {k: v / tw_sum for k, v in target_weights.items()}
        return self.generate_plan(db, user_id, target_weights)

    def format_plan(self, plan: RebalancePlan) -> str:
        if not plan.actions:
            return "No rebalancing actions required."

        lines: list[str] = [
            "=" * 60,
            "REBALANCE PLAN",
            "=" * 60,
            f"Portfolio Value: {plan.portfolio_value:,.2f} RUB",
            f"Total Trades:    {plan.total_trades}",
        ]

        if plan.portfolio_value > 0:
            lines.append(f"Turnover:        {plan.turnover:,.2f} RUB ({plan.turnover / plan.portfolio_value * 100:.1f}% of portfolio)")
        else:
            lines.append(f"Turnover:        {plan.turnover:,.2f} RUB")

        lines.append(f"Est. Commission: {plan.estimated_commission:,.2f} RUB")
        lines.append("")
        lines.append("Actions:")
        lines.append("-" * 60)

        for action in plan.actions:
            if action.action == "HOLD":
                lines.append(
                    f"  {action.ticker:6s} \u2192 HOLD  "
                    f"(w: {action.current_weight:.1%} \u2192 {action.target_weight:.1%}, "
                    f"dev: {action.deviation:+.1%})"
                )
            else:
                lines.append(
                    f"  {action.ticker:6s} \u2192 {action.action:4s} "
                    f"{action.quantity:>4d} @ est. {action.estimated_cost:>10,.2f} RUB  "
                    f"(w: {action.current_weight:.1%} \u2192 {action.target_weight:.1%}, "
                    f"dev: {action.deviation:+.1%})  [{action.reason}]"
                )

        if plan.sector_breaks:
            lines.extend(["", "Sector Limit Breaches:", "-" * 60])
            for sb in plan.sector_breaks:
                lines.append(f"  {sb['sector']:20s} {sb['weight']:.1%} > {sb['max_pct']:.0%} (excess: {sb['excess']:+.1%})")

        lines.extend(["", "=" * 60])
        return "\n".join(lines)


@dataclass
class BondLadderRung:
    ticker: str
    maturity_date: str
    duration_years: float | None
    yield_to_maturity: float | None
    coupon_rate: float | None
    credit_rating: str | None
    allocation_pct: float
    bucket: str  # short / mid / long
    reason: str


@dataclass
class BondLadderPlan:
    rungs: list[BondLadderRung]
    target_duration: float
    actual_duration: float
    duration_gap: float
    buckets: dict[str, float]


def build_bond_ladder(
    db: Any,
    target_duration: float = 3.0,
    max_rungs: int = 10,
) -> BondLadderPlan:
    """Build a bond ladder: bucket bonds by maturity into short (<2y), mid (2-5y), long (>5y)."""
    bonds = (
        db.query(BondOffering)
        .join(Instrument, BondOffering.instrument_id == Instrument.id)
        .filter(Instrument.instrument_type == "bond")
        .order_by(BondOffering.maturity_date.asc().nullslast())
        .limit(max_rungs)
        .all()
    )

    rungs: list[BondLadderRung] = []
    bucket_weights: dict[str, float] = {"short": 0.0, "mid": 0.0, "long": 0.0}
    total_duration = 0.0
    count = 0

    inst_ids = [b.instrument_id for b in bonds if b.instrument_id]
    all_instrs = db.query(Instrument).filter(Instrument.id.in_(inst_ids)).all() if inst_ids else []
    instr_map = {r.id: r for r in all_instrs}

    for b in bonds:
        if not b.maturity_date:
            continue
        years_to_maturity = (b.maturity_date - date.today()).days / 365.25
        if years_to_maturity < 0:
            continue

        if years_to_maturity <= 2:
            bucket = "short"
        elif years_to_maturity <= 5:
            bucket = "mid"
        else:
            bucket = "long"

        instr = instr_map.get(b.instrument_id)
        ticker = instr.ticker if instr else "?"

        dur = b.duration_years or years_to_maturity
        total_duration += dur
        count += 1
        bucket_weights[bucket] += 1.0

        rungs.append(
            BondLadderRung(
                ticker=ticker,
                maturity_date=b.maturity_date.isoformat(),
                duration_years=dur,
                yield_to_maturity=b.yield_to_maturity,
                coupon_rate=b.coupon_rate,
                credit_rating=b.credit_rating,
                allocation_pct=0.0,
                bucket=bucket,
                reason=f"Погашение через {years_to_maturity:.1f} лет",
            )
        )

    if count > 0:
        avg_duration = total_duration / count
        for r in rungs:
            r.allocation_pct = round(100.0 / len(rungs), 1)
        for k in bucket_weights:
            bucket_weights[k] = round(bucket_weights[k] / count * 100, 1)
    else:
        avg_duration = 0.0

    return BondLadderPlan(
        rungs=rungs,
        target_duration=target_duration,
        actual_duration=round(avg_duration, 2),
        duration_gap=round(target_duration - avg_duration, 2),
        buckets=bucket_weights,
    )


def duration_match_portfolio(
    db: Any,
    portfolio_value: float,
    target_duration: float = 3.0,
) -> list[dict[str, Any]]:
    """Match portfolio bond exposure to a target duration."""
    bonds = (
        db.query(BondOffering)
        .join(Instrument, BondOffering.instrument_id == Instrument.id)
        .filter(Instrument.instrument_type == "bond")
        .all()
    )

    inst_ids = [b.instrument_id for b in bonds if b.instrument_id]
    all_instrs = db.query(Instrument).filter(Instrument.id.in_(inst_ids)).all() if inst_ids else []
    instr_map = {r.id: r for r in all_instrs}

    candidates: list[dict[str, Any]] = []
    for b in bonds:
        dur = b.duration_years or 0
        if dur <= 0:
            continue
        instr = instr_map.get(b.instrument_id)
        ticker = instr.ticker if instr else "?"

        deviation = abs(dur - target_duration)
        score = max(0, 100 - deviation * 20)
        if b.credit_rating and b.credit_rating.startswith("A"):
            score += 10
        if b.yield_to_maturity:
            score += min(b.yield_to_maturity, 15)

        candidates.append({
            "ticker": ticker,
            "duration": round(dur, 2),
            "deviation": round(deviation, 2),
            "ytm": b.yield_to_maturity,
            "rating": b.credit_rating or "NR",
            "score": round(score, 1),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:10]


async def async_analyze_portfolio(
    user_id: int = 0,
    target_weights: dict[str, float] | None = None,
    max_sector_pct: float = 0.35,
    max_position_pct: float = 0.15,
    rebalance_threshold: float = 0.05,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
) -> list[dict[str, Any]]:
    from src.db.connection import get_session
    loop = asyncio.get_running_loop()
    engine = RebalancingEngine(
        max_sector_pct=max_sector_pct,
        max_position_pct=max_position_pct,
        rebalance_threshold=rebalance_threshold,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
    )
    return await loop.run_in_executor(
        None, engine.analyze_portfolio, get_session(), user_id, target_weights
    )


rebalancing_engine = RebalancingEngine()
