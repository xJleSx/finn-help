from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.analysis.bonds.new_bond_locator import find_new_bonds
from src.db.connection import get_session
from src.db.models import BondOffering, Instrument
from src.interfaces.telegram_guard import guard

logger = structlog.get_logger(__name__)


@guard()
async def bonds_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bonds in portfolio."""
    if not update.effective_message:
        return

    db = get_session()
    try:
        bonds = (
            db.query(Instrument, BondOffering)
            .join(BondOffering, BondOffering.instrument_id == Instrument.id)
            .filter(Instrument.instrument_type == "bond")
            .order_by(Instrument.ticker)
            .limit(15)
            .all()
        )

        if not bonds:
            await update.effective_message.reply_text("Нет данных об облигациях. Запустите `finn update` для загрузки.")
            return

        lines = ["<b>📊 Облигации</b>\n"]
        for inst, offering in bonds:
            ticker = inst.ticker
            name = (inst.full_name or ticker)[:30]
            ytm = offering.yield_to_maturity
            rating = offering.credit_rating or "—"
            maturity = offering.maturity_date.strftime("%d.%m.%Y") if offering.maturity_date else "—"
            ytm_str = f"{ytm:.1f}%" if ytm else "—"
            lines.append(
                f"<b>{ticker}</b> {name}\n"
                f"  YTM: {ytm_str} | Рейтинг: {rating}\n"
                f"  Погашение: {maturity}"
            )

        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()


@guard()
async def bond_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bond detail by ticker: /bond SU26238RMFS4"""
    if not update.effective_message:
        return
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Укажите тикер: /bond SU26238RMFS4")
        return

    ticker = args[0].upper()
    db = get_session()
    try:
        inst = db.query(Instrument).filter(Instrument.ticker == ticker, Instrument.instrument_type == "bond").first()
        if not inst:
            await update.effective_message.reply_text(f"Облигация {ticker} не найдена")
            return

        offering = db.query(BondOffering).filter(BondOffering.instrument_id == inst.id).order_by(BondOffering.offering_date.desc()).first()
        if not offering:
            await update.effective_message.reply_text(f"Нет данных о выпуске для {ticker}")
            return

        text = (
            f"<b>{inst.full_name or ticker}</b>\n"
            f"Тикер: {ticker}\n"
            f"ISIN: {offering.isin or inst.isin or '—'}\n"
            f"Номинал: {offering.nominal_price or inst.nominal or '—':.0f} ₽\n"
            f"Купон: {offering.coupon_rate or '—':.1f}% ({offering.coupon_type or 'фикс'})\n"
            f"Период: {offering.coupon_period_days or '—'} дн.\n"
            f"YTM: {offering.yield_to_maturity or '—':.1f}%\n"
            f"Дюрация: {offering.duration_years or '—':.1f} лет\n"
            f"Рейтинг: {offering.credit_rating or '—'}\n"
            f"Погашение: {offering.maturity_date.strftime('%d.%m.%Y') if offering.maturity_date else '—'}\n"
            f"Амортизация: {'да' if offering.has_amortization else 'нет'}\n"
            f"Объём: {offering.volume:,.0f} ₽" if offering.volume else ""
        )
        await update.effective_message.reply_text(text, parse_mode="HTML")
    finally:
        db.close()


@guard()
async def new_bonds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return

    from src.trading.brokers.tbank import get_available_bond_tickers

    db = get_session()
    try:
        available_tickers = await get_available_bond_tickers()
        bonds = find_new_bonds(db, max_results=10, available_tickers=available_tickers)

        if not bonds:
            await update.effective_message.reply_text("Новых облигаций (без первой выплаты купона) не найдено.")
            return

        lines = ["<b>🆕 Новые облигации</b> (до 2 выплаченных купонов)\n"]
        if available_tickers is not None:
            lines.insert(0, "✅ Доступны в Т-Банк\n")
        for i, b in enumerate(bonds, 1):
            ticker = b["ticker"]
            company = b.get("company_name") or ""
            ytm = f'{b["yield_to_maturity"]:.1f}%' if b["yield_to_maturity"] else "—"
            coupon = f'{b["coupon_rate"]:.1f}%' if b["coupon_rate"] else "—"
            rating = b["credit_rating"]
            first_coupon = b["first_coupon_date"]
            days = b["days_to_first_coupon"]
            fcd = f"{first_coupon} (через {days} дн.)" if first_coupon and days is not None else "—"
            header = f'{i}. <b>{ticker}</b>'
            if company:
                header += f' — {company}'
            lines.append(
                f'{header} — {coupon} · YTM {ytm} · {rating}\n'
                f'   След. купон: {fcd}'
            )

        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()
