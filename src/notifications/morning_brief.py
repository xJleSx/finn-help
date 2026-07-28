import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, cast

from src.db.connection import get_session
from src.db.models import BondOffering, Instrument, Price
from src.interfaces.telegram_helpers import get_portfolio_positions, html_escape
from src.notifications.calendar_checker import (
    format_days,
    get_upcoming_events,
)

logger = logging.getLogger(__name__)


def build_morning_brief() -> str:
    today = date.today()
    lines = [
        "📊 <b>Брифинг на {}</b>\n".format(today.strftime("%d.%m.%Y")),
    ]
    portfolio_value, day_pnl_pct, day_pnl_abs = _get_portfolio_summary()
    pnl_line = "💰 Портфель: {:,.0f} ₽ | P&L день: {:+.2%}".format(
        portfolio_value, day_pnl_pct
    )
    if abs(day_pnl_abs or 0) > 0.5:
        pnl_line += " ({:+,.0f} ₽)".format(day_pnl_abs)
    lines.append(pnl_line)
    lines.append("")

    cal = get_upcoming_events(days_ahead=14)
    today_events = [e for e in cal.redemptions if e.days_until == 0]
    for ev in today_events:
        lines.append("🔔 <b>Сегодня:</b>")
        lines.append("• {} — ПОГАШЕНИЕ".format(html_escape(ev.ticker)))
        lines.append("  Вернутся: ~{:.0f} ₽ номинала".format(ev.total_amount))
        if ev.amount_per_unit > 0:
            lines.append("  + купон {:.1f} ₽".format(ev.amount_per_unit * ev.quantity))
        reinvest_plan = _generate_reinvestment_plan(ev.total_amount)
        if reinvest_plan:
            lines.append("  💡 Рекомендация: {}".format(reinvest_plan))
        lines.append("")

    upcoming_redemptions = [e for e in cal.redemptions if 1 <= e.days_until <= 7]
    upcoming_coupons = [e for e in cal.coupons if e.days_until <= 7]

    if upcoming_redemptions or upcoming_coupons:
        lines.append("📅 <b>Ближайшие события (7 дней):</b>")
        for ev in upcoming_redemptions:
            lines.append("• {} — погашение через {}".format(html_escape(ev.ticker), format_days(ev.days_until)))
        for ev in upcoming_coupons:
            lines.append("• {} — купон {:.0f} ₽ через {}".format(html_escape(ev.ticker), ev.total_amount, format_days(ev.days_until)))
        lines.append("")

    movers = _get_top_movers(limit=5)
    if movers:
        lines.append("📈 <b>Движения:</b>")
        for m in movers:
            comment = ""
            if abs(m["change_pct"]) > 1:
                comment = " (значительное)"
            direction = "🟢" if m["change_pct"] > 0 else "🔴"
            lines.append("• {} {}: {:+.1%}{}".format(direction, html_escape(m["ticker"]), m["change_pct"], comment))
        lines.append("")

    risks = _check_risks()
    if risks:
        lines.append("⚠️ <b>Риски:</b>")
        for r in risks:
            lines.append("• {}".format(r))
        lines.append("")
    else:
        lines.append("⚠️ <b>Риски:</b>")
        lines.append("• Нет активных алертов")
        lines.append("")

    lines.append("📅 <b>Ближайшие события:</b>")
    next_coupons = [e for e in cal.coupons if 7 < e.days_until <= 30]
    for ev in next_coupons[:3]:
        lines.append("• {}.{} — купон {} (+{:.0f} ₽)".format(
            ev.event_date.day, ev.event_date.month,
            html_escape(ev.name.split(",")[0] if "," in ev.name else ev.name),
            ev.total_amount,
        ))
    next_redemptions = [e for e in cal.redemptions if 7 < e.days_until <= 30]
    for ev in next_redemptions[:2]:
        lines.append("• {}.{} — погашение {} ({:.0f} ₽)".format(
            ev.event_date.day, ev.event_date.month,
            html_escape(ev.ticker), ev.total_amount,
        ))
    next_deposit = _get_next_deposit()
    if next_deposit:
        lines.append("• {}.{} — пополнение {:+,.0f} ₽".format(
            next_deposit.day, next_deposit.month, next_deposit.amount,
        ))
    lines.append("")

    return "\n".join(lines)


def _get_portfolio_summary() -> tuple[float, float, float]:
    db = get_session()
    try:
        rows = get_portfolio_positions(db)
        total_value = sum(r["value"] for r in rows)
        day_pnl_abs = 0.0
        for r in rows:
            quantity = r["quantity"]
            cur = r["current_price"]
            prices = (
                db.query(Price)
                .join(Instrument)
                .filter(Instrument.ticker == r["ticker"])
                .order_by(Price.date.desc())
                .limit(2)
                .all()
            )
            if len(prices) >= 2 and prices[-1].close:
                yesterday = cast(float, prices[-1].close)
                pnl = (cur - yesterday) * quantity
                day_pnl_abs += pnl
        day_pnl_pct = day_pnl_abs / total_value if total_value > 0 else 0.0
        return total_value, day_pnl_pct, day_pnl_abs
    except Exception:
        logger.exception("brief_summary_error")
        return 0.0, 0.0, 0.0
    finally:
        db.close()


def _get_top_movers(limit: int = 5) -> list[dict[str, Any]]:
    db = get_session()
    try:
        rows = get_portfolio_positions(db)
        movers = []
        for r in rows:
            cur = r["current_price"]
            prices = (
                db.query(Price)
                .join(Instrument)
                .filter(Instrument.ticker == r["ticker"])
                .order_by(Price.date.desc())
                .limit(2)
                .all()
            )
            if len(prices) >= 2 and prices[-1].close:
                prev = cast(float, prices[-1].close)
                change = (cur - prev) / prev
                movers.append({"ticker": r["ticker"], "change_pct": change})
        movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        return movers[:limit]
    finally:
        db.close()


def _check_risks() -> list[str]:
    risks: list[str] = []
    db = get_session()
    try:
        from src.analysis.metrics import compute_max_drawdown
        rows = get_portfolio_positions(db)
        if not rows:
            return risks
        values = [r["current_price"] * r["quantity"] for r in rows if r["quantity"] > 0]
        if not values:
            return risks
        prices_by_ticker: dict[str, list[float]] = {}
        for r in rows:
            prices = (
                db.query(Price)
                .join(Instrument)
                .filter(Instrument.ticker == r["ticker"])
                .order_by(Price.date.desc())
                .limit(60)
                .all()
            )
            vals = [cast(float, p.close) for p in reversed(prices) if p.close]
            if vals:
                prices_by_ticker[r["ticker"]] = vals
        if prices_by_ticker:
            total_hist = []
            min_len = min(len(v) for v in prices_by_ticker.values())
            for i in range(min_len):
                day_total = sum(
                    prices_by_ticker[t][i] * next(
                        (r2["quantity"] for r2 in rows if r2["ticker"] == t), 0
                    )
                    for t in prices_by_ticker
                )
                total_hist.append(day_total)
            if total_hist:
                mdd = compute_max_drawdown(total_hist)
                if mdd < -0.05:
                    risks.append("Просадка портфеля: {:.1%}".format(mdd))
        for r in rows:
            inst = db.query(Instrument).filter_by(ticker=r["ticker"]).first()
            if inst:
                offering = db.query(BondOffering).filter_by(instrument_id=inst.id).order_by(BondOffering.offering_date.desc()).first()
                if offering and offering.credit_rating:
                    rating = str(offering.credit_rating).upper()
                    if rating in ("CCC", "CC", "C", "D"):
                        risks.append("{} ({}): высокорисковая облигация".format(html_escape(r["ticker"]), rating))
        return risks
    except Exception:
        logger.exception("error checking risks")
        return risks
    finally:
        db.close()


@dataclass
class DepositEvent:
    day: int
    month: int
    amount: float


def _get_next_deposit() -> Optional[DepositEvent]:
    today = date.today()
    day = 25
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
    amount = 4000
    return DepositEvent(day=deposit_date.day, month=deposit_date.month, amount=amount)


def _generate_reinvestment_plan(amount: float) -> str:
    if amount < 500:
        return "оставить на накопительном счёте"
    try:
        import asyncio

        from src.portfolio.allocator import allocator
        picks = asyncio.run(allocator.recommend(capital=amount))
        if not picks:
            return None
        tops = [p for p in picks[:3]]
        plan_parts = []
        for p in tops:
            ticker = p.get("ticker", "?")
            price = p.get("price", 0) or 1000
            qty = max(1, int(amount / (price * len(tops))))
            plan_parts.append("{} +{} шт (~{:.0f} ₽)".format(ticker, qty, price * qty))
        return ", ".join(plan_parts)
    except Exception:
        logger.exception("reinvestment_plan_error")
        return None
