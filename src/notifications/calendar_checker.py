import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from src.db.connection import get_session
from src.db.models import BondCouponSchedule, BondOffering, Instrument, Portfolio

logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    event_type: str
    ticker: str
    name: str
    event_date: date
    amount_per_unit: float
    quantity: float
    total_amount: float
    days_until: int


@dataclass
class CalendarResult:
    coupons: list[CalendarEvent] = field(default_factory=list)
    redemptions: list[CalendarEvent] = field(default_factory=list)


def get_upcoming_events(days_ahead: int = 14) -> CalendarResult:
    result = CalendarResult()
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    db = get_session()
    try:
        portfolio_positions = db.query(Portfolio).all()
        for pos in portfolio_positions:
            inst = db.query(Instrument).filter_by(id=pos.instrument_id).first()
            if not inst:
                continue
            ticker = inst.ticker
            name = inst.full_name or ticker
            inst_type = inst.instrument_type or ""
            quantity = float(pos.quantity or 0)

            offering = db.query(BondOffering).filter_by(instrument_id=inst.id).order_by(BondOffering.offering_date.desc()).first()

            if inst_type == "bond" and offering and quantity > 0:
                coupon_period = offering.coupon_period_days or 182
                coupon_rate = float(offering.coupon_rate or 0)
                nominal = float(offering.nominal_price or inst.nominal or 1000)

                coupon_size = nominal * (coupon_rate / 100) * (coupon_period / 365) if coupon_rate > 0 else 0

                if coupon_size > 0:
                    upcoming = (
                        db.query(BondCouponSchedule)
                        .filter(
                            BondCouponSchedule.instrument_id == inst.id,
                            BondCouponSchedule.coupon_date >= today,
                            BondCouponSchedule.coupon_date <= cutoff,
                        )
                        .order_by(BondCouponSchedule.coupon_date)
                        .all()
                    )
                    for c in upcoming:
                        cd = c.coupon_date
                        if isinstance(cd, str):
                            cd = datetime.strptime(cd[:10], "%Y-%m-%d").date()
                        days_until = (cd - today).days
                        amount = float(c.coupon_value or 0)
                        if amount <= 0:
                            amount = coupon_size
                        result.coupons.append(
                            CalendarEvent(
                                event_type="coupon",
                                ticker=ticker,
                                name=name,
                                event_date=cd,
                                amount_per_unit=amount,
                                quantity=quantity,
                                total_amount=amount * quantity,
                                days_until=days_until,
                            )
                        )

                mat_date = offering.maturity_date
                if mat_date:
                    if isinstance(mat_date, str):
                        mat_date = datetime.strptime(mat_date[:10], "%Y-%m-%d").date()
                    days_until = (mat_date - today).days
                    if 0 <= days_until <= days_ahead:
                        face_value = nominal
                        result.redemptions.append(
                            CalendarEvent(
                                event_type="redemption",
                                ticker=ticker,
                                name=name,
                                event_date=mat_date,
                                amount_per_unit=face_value,
                                quantity=quantity,
                                total_amount=face_value * quantity,
                                days_until=days_until,
                            )
                        )
        return result
    finally:
        db.close()


COUPON_ADVICE_TEXT = """💡 Совет: Не покупай эту облигацию за 1–2 дня до купонной даты — НКД будет максимальным. Лучше через 1–2 дня после выплаты."""

REDEMPTION_ADVICE_TEXT = """💡 При погашении деньги «выпадают» из доходности. Если не реинвестировать в течение 3–5 дней — потеря ~0.5% годовых на простое лежании."""


def format_coupon_alert(event: CalendarEvent, days_to_show: int) -> str:
    header = "🔔 Через {}: купон {}".format(
        format_days(days_to_show),
        event.ticker,
    )
    lines = [
        header,
        "",
        "💵 Сумма: {:.2f} ₽ ({:.0f} шт × {:.2f} ₽)".format(
            event.total_amount, event.quantity, event.amount_per_unit
        ),
        "📅 Зачисление: {}".format(event.event_date.strftime("%d.%m.%Y")),
        "",
    ]
    if days_to_show <= 3:
        lines.append(COUPON_ADVICE_TEXT)
    return "\n".join(lines)


def format_redemption_alert(event: CalendarEvent, days_to_show: int) -> str:
    header_text = {
        7: "🚨 ВНИМАНИЕ: Погашение {} через 7 дней".format(event.ticker),
        3: "🚨 ВНИМАНИЕ: Погашение {} через 3 дня".format(event.ticker),
        1: "🚨 ВНИМАНИЕ: Погашение {} ЗАВТРА".format(event.ticker),
        0: "🚨 СЕГОДНЯ: Погашение {}".format(event.ticker),
    }.get(days_to_show, "📅 Погашение {} через {} дней".format(event.ticker, days_to_show))
    lines = [
        header_text,
        "",
        "📅 {} вернётся: {:.0f} ₽ номинала".format(
            event.event_date.strftime("%d.%m.%Y"), event.total_amount
        ),
    ]
    if event.amount_per_unit > 0:
        lines.append("💰 + купон {:.1f} ₽".format(event.amount_per_unit * event.quantity))
    lines.append("")
    if days_to_show <= 3:
        lines.append(REDEMPTION_ADVICE_TEXT)
    return "\n".join(lines)


def format_days(days: int) -> str:
    days_map = {0: "сегодня", 1: "завтра"}
    return days_map.get(days, "{} дней".format(days) if days <= 4 else "{} дней".format(days))
