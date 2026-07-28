import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional, cast

from src.db.connection import get_session
from src.db.models import BondCouponSchedule, Instrument, Portfolio, Price
from src.interfaces.telegram_helpers import get_portfolio_positions

logger = logging.getLogger(__name__)

NDFL_RATE = 0.13
LDV_YEARS = 3


@dataclass
class TaxReport:
    period: str
    coupon_income: float
    coupon_tax: float
    capital_gain: float
    capital_tax: float
    ldv_applicable: bool
    total_tax_due: float
    payment_date: str


def generate_tax_report() -> Optional[TaxReport]:
    today = date.today()
    from calendar import monthrange
    _, last_day = monthrange(today.year, today.month)
    last_month = today.replace(day=1) - timedelta(days=1)
    month_start = last_month.replace(day=1)
    month_end = last_month.replace(day=last_day)
    db = get_session()
    try:
        coupon_income = 0.0
        rows = get_portfolio_positions(db)
        for r in rows:
            inst = db.query(Instrument).filter_by(ticker=r["ticker"]).first()
            if not inst:
                continue
            coupons = (
                db.query(BondCouponSchedule)
                .filter(
                    BondCouponSchedule.instrument_id == inst.id,
                    BondCouponSchedule.coupon_date >= month_start,
                    BondCouponSchedule.coupon_date <= month_end,
                )
                .all()
            )
            for c in coupons:
                amount = (c.coupon_value or 0) * r["quantity"]
                coupon_income += amount
        coupon_tax = coupon_income * NDFL_RATE
        capital_gain = _compute_capital_gain(db, rows, month_start, month_end)
        capital_tax = capital_gain * NDFL_RATE if capital_gain > 0 else 0.0
        ldv_applicable = _check_ldv_eligibility(db)
        total_tax = coupon_tax + capital_tax
        period = month_start.strftime("%B %Y")
        payment_date = "до 1." + month_end.strftime("%m.%Y")
        return TaxReport(
            period=period,
            coupon_income=coupon_income,
            coupon_tax=coupon_tax,
            capital_gain=capital_gain,
            capital_tax=capital_tax,
            ldv_applicable=ldv_applicable,
            total_tax_due=total_tax,
            payment_date=payment_date,
        )
    except Exception:
        logger.exception("tax_report_error")
        return None
    finally:
        db.close()


def _compute_capital_gain(
    db: Any,
    rows: list[dict[str, Any]],
    start: date,
    end: date,
) -> float:
    total_gain = 0.0
    for r in rows:
        changes = (
            db.query(Price)
            .join(Instrument)
            .filter(
                Instrument.ticker == r["ticker"],
                Price.date >= start,
                Price.date <= end,
            )
            .order_by(Price.date)
            .all()
        )
        if len(changes) >= 2 and changes[0].close and changes[-1].close:
            price_change = (cast(float, changes[-1].close) - cast(float, changes[0].close))
            total_gain += price_change * r["quantity"]
    return total_gain


def _check_ldv_eligibility(db: Any) -> bool:
    try:
        from src.db.models import Transaction
        today = date.today()
        rows = db.query(Portfolio).all()
        for p in rows:
            first_tx = (
                db.query(Transaction)
                .filter_by(instrument_id=p.instrument_id)
                .order_by(Transaction.date)
                .first()
            )
            if not first_tx or not first_tx.date:
                continue
            bought = first_tx.date
            if isinstance(bought, str):
                bought = datetime.strptime(bought[:10], "%Y-%m-%d").date()
            years_held = (today - bought).days / 365.0
            if years_held >= LDV_YEARS:
                return True
    except Exception:
        logger.debug("LDV check failed")
    return False


def format_tax_report(report: TaxReport) -> str:
    lines = [
        "📊 <b>Налоговый отчёт ({})</b>\n".format(report.period),
        "💰 Купонный доход: {:.0f} ₽".format(report.coupon_income),
        "💸 НДФЛ 13%: −{:.2f} ₽".format(report.coupon_tax),
        "",
        "📈 Прирост капитала: {:+.0f} ₽".format(report.capital_gain),
    ]
    if report.capital_tax > 0:
        lines.append("💸 Налог: −{:.2f} ₽".format(report.capital_tax))
    else:
        lines.append("💸 Налог: 0 ₽ (убыток или ЛДВ)")
    lines.append("")
    if report.ldv_applicable:
        lines.append("🎁 ЛДВ ({}+ лет): Применимо".format(LDV_YEARS))
    else:
        lines.append("🎁 ЛДВ ({}+ лет): Не применимо".format(LDV_YEARS))
    lines.append("")
    lines.append("Итого к уплате: {:.2f} ₽".format(report.total_tax_due))
    lines.append("Дата списания: {}".format(report.payment_date))
    lines.append("")
    lines.append("💡 Совет: Переведи портфель на ИИС-3 —")
    lines.append("  вычет на взнос до 52 000 ₽/год.")
    return "\n".join(lines)
