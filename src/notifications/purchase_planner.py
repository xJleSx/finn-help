import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from src.db.connection import get_session
from src.db.models import BondCouponSchedule, BondOffering, Instrument
from src.interfaces.telegram_helpers import html_escape

logger = logging.getLogger(__name__)

DEPOSIT_AMOUNT = 4000
DEPOSIT_DAY = 25


@dataclass
class PurchasePlan:
    deposit_amount: float
    deposit_date: date
    recommendations: list[dict[str, Any]]
    warnings: list[str]


def generate_purchase_plan() -> Optional[PurchasePlan]:
    today = date.today()
    day = DEPOSIT_DAY
    next_month = today.month
    next_year = today.year
    if today.day >= day:
        next_month += 1
        if next_month > 12:
            next_month = 1
            next_year += 1
    try:
        deposit_date = date(next_year, next_month, day)
    except ValueError:
        return None
    days_until = (deposit_date - today).days
    if days_until > 3 or days_until < 0:
        return None
    try:
        import asyncio

        from src.portfolio.allocator import allocator
        picks = asyncio.run(allocator.recommend(capital=DEPOSIT_AMOUNT))
        if not picks:
            return None
        recommendations = []
        warnings = []
        remaining = DEPOSIT_AMOUNT
        for p in picks[:5]:
            ticker = p.get("ticker", "?")
            price = p.get("price", 0) or 1000
            max_qty = max(1, int(remaining / price))
            if max_qty == 0:
                continue
            cost = max_qty * price
            remaining -= cost
            inst_type = p.get("instrument_type", "")
            if inst_type == "bond":
                db = get_session()
                try:
                    inst = db.query(Instrument).filter_by(ticker=ticker).first()
                    if inst:
                        next_coupon = (
                            db.query(BondCouponSchedule)
                            .filter(
                                BondCouponSchedule.instrument_id == inst.id,
                                BondCouponSchedule.coupon_date >= date.today(),
                            )
                            .order_by(BondCouponSchedule.coupon_date)
                            .first()
                        )
                        if next_coupon:
                            cd = next_coupon.coupon_date
                            if isinstance(cd, str):
                                cd = datetime.strptime(cd[:10], "%Y-%m-%d").date()
                            if abs((cd - deposit_date).days) <= 2:
                                warnings.append("⚠ {}: купон {}, не покупать за 1–2 дня до".format(
                                    html_escape(ticker),
                                    cd.strftime("%d.%m.%Y"),
                                ))
                        offering = db.query(BondOffering).filter_by(instrument_id=inst.id).order_by(BondOffering.offering_date.desc()).first()
                        spread = p.get("spread_pct", 0)
                        if offering:
                            if spread > 1.0:
                                warnings.append("⚠ {}: спред >1% (корпоративные)".format(html_escape(ticker)))
                            elif spread > 0.3 and ticker.startswith("SU"):
                                warnings.append("⚠ {}: спред >0.3% (ОФЗ)".format(html_escape(ticker)))
                finally:
                    db.close()
            recommendations.append({
                "ticker": ticker,
                "quantity": max_qty,
                "price": price,
                "cost": cost,
            })
        return PurchasePlan(
            deposit_amount=DEPOSIT_AMOUNT,
            deposit_date=deposit_date,
            recommendations=recommendations,
            warnings=warnings,
        )
    except Exception:
        logger.exception("purchase_plan_error")
        return None


def format_purchase_plan(plan: PurchasePlan) -> str:
    lines = [
        "📅 Пополнение {}: {:+,.0f} ₽\n".format(
            plan.deposit_date.strftime("%d.%m.%Y"), plan.deposit_amount
        ),
        "📋 Рассчитанный план покупок:\n",
    ]
    for i, rec in enumerate(plan.recommendations, 1):
        lines.append("{}. {} +{} шт (~{:.0f} ₽)".format(
            i,
            html_escape(rec["ticker"]),
            rec["quantity"],
            rec["cost"],
        ))
    remaining = plan.deposit_amount - sum(r["cost"] for r in plan.recommendations)
    if remaining > 0:
        lines.append("\n💵 Остаток: {:.0f} ₽ → на накопительный счёт".format(remaining))
    if plan.warnings:
        lines.append("")
        for w in plan.warnings:
            lines.append(w)
    lines.append("")
    lines.append("[Подтвердить] [Изменить] [Напомнить {} в 10:00]".format(
        plan.deposit_date.strftime("%d.%m.%Y"),
    ))
    return "\n".join(lines)
