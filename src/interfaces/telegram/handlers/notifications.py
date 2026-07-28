
import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.interfaces.telegram_guard import guard

logger = structlog.get_logger(__name__)


@guard()
async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("⏳ Формирую брифинг...")
    try:
        from src.notifications.morning_brief import build_morning_brief
        text = build_morning_brief()
        await update.effective_message.reply_text(text, parse_mode="HTML")
    except Exception:
        logger.exception("brief_handler_error")
        await update.effective_message.reply_text("❌ Не удалось сформировать брифинг.")


@guard()
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Использование: /buy TICKER КОЛИЧЕСТВО\n"
            "Например: /buy SU26254RMFS2 2"
        )
        return
    ticker = args[0].upper()
    try:
        quantity = int(args[1])
    except ValueError:
        await update.effective_message.reply_text("Количество должно быть числом.")
        return
    await _show_purchase_preview(update, ticker, quantity)


@guard()
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Использование: /sell TICKER КОЛИЧЕСТВО\n"
            "Например: /sell SBER 10"
        )
        return
    ticker = args[0].upper()
    try:
        quantity = int(args[1])
    except ValueError:
        await update.effective_message.reply_text("Количество должно быть числом.")
        return
    from src.db.connection import get_session
    from src.db.models import Instrument, Portfolio
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            await update.effective_message.reply_text(f"Инструмент {ticker} не найден")
            return
        pos = db.query(Portfolio).filter_by(instrument_id=inst.id).first()
        if not pos:
            await update.effective_message.reply_text(f"{ticker} нет в портфеле")
            return
        if quantity > pos.quantity:
            await update.effective_message.reply_text(
                f"У вас только {pos.quantity:.0f} шт {ticker}, нельзя продать {quantity}"
            )
            return
    finally:
        db.close()
    await _show_sell_preview(update, ticker, quantity)


async def _show_purchase_preview(update: Update, ticker: str, quantity: int) -> None:
    from src.db.connection import get_session
    from src.db.models import BondOffering, Instrument, Price
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            await update.effective_message.reply_text(f"Инструмент {ticker} не найден")
            return
        price_rec = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
        if not price_rec or not price_rec.close:
            await update.effective_message.reply_text(f"Нет цены для {ticker}")
            return
        price = float(price_rec.close)
        inst_type = inst.instrument_type or ""
        is_bond = inst_type == "bond"
        nkd = 0.0
        if is_bond and price < 500:
            nominal = inst.nominal or 1000
            price = price * nominal / 100
        if is_bond:
            offering = db.query(BondOffering).filter_by(instrument_id=inst.id).order_by(BondOffering.offering_date.desc()).first()
            if offering and offering.extra and isinstance(offering.extra, dict):
                nkd = float(offering.extra.get("accrued_interest", 0)) * quantity
        subtotal = price * quantity
        commission = max(subtotal * 0.0004, 0.01)
        total = subtotal + nkd + commission
        lines = [
            "✅ <b>Рассчитано:</b>\n",
            "Цена: {:.2f} ₽ × {} = {:.2f} ₽".format(price, quantity, subtotal),
        ]
        if nkd > 0:
            lines.append("НКД: +{:.2f} ₽".format(nkd))
        lines.append("Комиссия: {:.2f} ₽".format(commission))
        lines.append("ИТОГО: {:.2f} ₽".format(total))
        lines.append("")
        lines.append("[Подтвердить покупку]")
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception:
        logger.exception("purchase_preview_error")
        await update.effective_message.reply_text("❌ Ошибка расчёта покупки.")
    finally:
        db.close()


async def _show_sell_preview(update: Update, ticker: str, quantity: int) -> None:
    from src.db.connection import get_session
    from src.db.models import Instrument, Portfolio, Price
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            return
        price_rec = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
        if not price_rec or not price_rec.close:
            await update.effective_message.reply_text(f"Нет цены для {ticker}")
            return
        price = float(price_rec.close)
        inst_type = inst.instrument_type or ""
        is_bond = inst_type == "bond"
        nkd = 0.0
        if is_bond and price < 500:
            nominal = inst.nominal or 1000
            price = price * nominal / 100
        pos = db.query(Portfolio).filter_by(instrument_id=inst.id).first()
        avg_price = float(pos.avg_price) if pos and pos.avg_price else 0
        subtotal = price * quantity
        commission = max(subtotal * 0.0004, 0.01)
        proceeds = subtotal - commission
        pnl = (price - avg_price) * quantity if avg_price > 0 else 0
        lines = [
            "✅ <b>Рассчитано:</b>\n",
            "Цена: {:.2f} ₽ × {} = {:.2f} ₽".format(price, quantity, subtotal),
        ]
        if nkd > 0:
            lines.append("НКД: +{:.2f} ₽".format(nkd))
        lines.append("Комиссия: {:.2f} ₽".format(commission))
        lines.append("К получению: {:.2f} ₽".format(proceeds))
        if avg_price > 0:
            lines.append("P&L: {:+.2f} ₽ ({:+.2%})".format(pnl, (price - avg_price) / avg_price))
        lines.append("")
        lines.append("[Подтвердить продажу]")
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception:
        logger.exception("sell_preview_error")
        await update.effective_message.reply_text("❌ Ошибка расчёта продажи.")
    finally:
        db.close()


@guard()
async def benchmark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("⏳ Сравниваю с рынком...")
    try:
        from src.notifications.benchmark_comparison import compare_benchmarks, format_benchmark_comparison
        cmp = compare_benchmarks(period_days=7)
        if cmp:
            text = format_benchmark_comparison(cmp)
            await update.effective_message.reply_text(text, parse_mode="HTML")
        else:
            await update.effective_message.reply_text("Недостаточно данных для сравнения.")
    except Exception:
        logger.exception("benchmark_handler_error")
        await update.effective_message.reply_text("❌ Ошибка сравнения с рынком.")


@guard()
async def taxreport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("⏳ Формирую налоговый отчёт...")
    try:
        from src.notifications.tax_report import format_tax_report, generate_tax_report
        report = generate_tax_report()
        if report:
            text = format_tax_report(report)
            await update.effective_message.reply_text(text, parse_mode="HTML")
        else:
            await update.effective_message.reply_text("Недостаточно данных для отчёта.")
    except Exception:
        logger.exception("tax_handler_error")
        await update.effective_message.reply_text("❌ Ошибка формирования отчёта.")
