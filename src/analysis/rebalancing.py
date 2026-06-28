from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.db.models import Instrument, Portfolio, Price, Signal
from src.notifications import RebalanceAlert

logger = logging.getLogger(__name__)

DEFAULT_COMMISSION_RATE = 0.0005


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
    ) -> None:
        self.max_sector_pct = max_sector_pct
        self.max_position_pct = max_position_pct
        self.rebalance_threshold = rebalance_threshold

    def analyze_portfolio(
        self,
        db: Any,
        user_id: int = 0,
        target_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        positions = db.query(Portfolio).filter_by(user_id=user_id).all()
        if not positions:
            return []

        portfolio_items: list[dict[str, Any]] = []
        total_value = 0.0

        for pos in positions:
            instr = db.query(Instrument).filter_by(id=pos.instrument_id).first()
            if not instr:
                continue
            price = (
                db.query(Price)
                .filter_by(instrument_id=instr.id)
                .order_by(Price.date.desc())
                .first()
            )
            if not price or not price.close:
                continue
            current_price = float(price.close)
            value = current_price * float(pos.quantity)
            total_value += value
            portfolio_items.append({
                "ticker": instr.ticker,
                "sector": instr.sector or "Прочее",
                "quantity": float(pos.quantity),
                "current_price": current_price,
                "value": value,
                "instrument_id": instr.id,
            })

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

            results.append({
                "ticker": ticker,
                "sector": item["sector"],
                "current_weight": round(current_weight, 4),
                "target_weight": round(target_weight, 4),
                "deviation": round(deviation, 4),
                "current_price": item["current_price"],
                "quantity": int(item["quantity"]),
                "value": round(item["value"], 2),
                "alerts": alerts,
            })

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
                actions=[], total_trades=0, estimated_commission=0.0,
                turnover=0.0, portfolio_value=0.0, sector_breaks=[],
            )

        portfolio_value = sum(a["value"] for a in analysis)

        signals_map: dict[str, dict[str, Any]] = {}
        for a in analysis:
            ticker = a["ticker"]
            instr = db.query(Instrument).filter_by(ticker=ticker).first()
            if instr:
                signal = (
                    db.query(Signal)
                    .filter_by(instrument_id=instr.id)
                    .order_by(Signal.date.desc())
                    .first()
                )
                if signal:
                    signals_map[ticker] = {
                        "action": signal.action,
                        "confidence": signal.confidence or 0.0,
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

            signal_info = signals_map.get(ticker, {})
            signal_action = signal_info.get("action", "HOLD")
            confidence = signal_info.get("confidence", 0.0)

            abs_dev = abs(deviation)

            if abs_dev < self.rebalance_threshold:
                actions.append(RebalanceAction(
                    ticker=ticker,
                    current_weight=current_weight,
                    target_weight=target_weight,
                    deviation=deviation,
                    action="HOLD",
                    quantity=0,
                    estimated_cost=0.0,
                    reason="within threshold",
                ))
                continue

            instr = db.query(Instrument).filter_by(ticker=ticker).first()
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
                    actions.append(RebalanceAction(
                        ticker=ticker,
                        current_weight=current_weight,
                        target_weight=target_weight,
                        deviation=deviation,
                        action="SELL",
                        quantity=sell_quantity,
                        estimated_cost=round(cost, 2),
                        reason="; ".join(reason_parts),
                    ))
                    total_turnover += cost
                    alerts.append(RebalanceAlert(
                        ticker=ticker,
                        current_pct=current_weight,
                        target_pct=target_weight,
                        deviation_pct=deviation,
                        reason="; ".join(reason_parts),
                    ))
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
                    actions.append(RebalanceAction(
                        ticker=ticker,
                        current_weight=current_weight,
                        target_weight=target_weight,
                        deviation=deviation,
                        action="BUY",
                        quantity=buy_quantity,
                        estimated_cost=round(cost, 2),
                        reason="; ".join(reason_parts),
                    ))
                    total_turnover += cost
                    alerts.append(RebalanceAlert(
                        ticker=ticker,
                        current_pct=current_weight,
                        target_pct=target_weight,
                        deviation_pct=deviation,
                        reason="; ".join(reason_parts),
                    ))

        sector_breaks = self._check_sector_limits(analysis)
        commission_rate = DEFAULT_COMMISSION_RATE
        estimated_commission = round(total_turnover * commission_rate, 2)

        if alerts:
            logger.info("Generated %d rebalance alerts", len(alerts))

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
                breaks.append({
                    "sector": sector,
                    "weight": round(weight, 4),
                    "max_pct": self.max_sector_pct,
                    "excess": round(weight - self.max_sector_pct, 4),
                })
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
                    trade["order_id"] = order.get("order_id")
                    trade["executed_price"] = order.get("executed_price")
                    trade["commission"] = order.get("commission")
                    trade["status"] = "submitted"
                except Exception as e:
                    logger.error("Failed to execute %s %s: %s", action.action, action.ticker, e)
                    trade["status"] = "failed"
                    trade["error"] = str(e)

            trades.append(trade)

        return trades

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
            lines.append(
                f"Turnover:        {plan.turnover:,.2f} RUB "
                f"({plan.turnover / plan.portfolio_value * 100:.1f}% of portfolio)"
            )
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
                lines.append(
                    f"  {sb['sector']:20s} {sb['weight']:.1%} > {sb['max_pct']:.0%} "
                    f"(excess: {sb['excess']:+.1%})"
                )

        lines.extend(["", "=" * 60])
        return "\n".join(lines)


rebalancing_engine = RebalancingEngine()
