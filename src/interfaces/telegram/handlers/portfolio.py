import contextlib
import io
from typing import Any, Optional, cast

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.analysis.stress import (
    StressTester,
    format_portfolio_for_stress,
)
from src.config import settings
from src.db.connection import get_session
from src.db.models import Instrument
from src.db.models import Portfolio as PortModel
from src.interfaces.telegram.messages import _reply_with_allocation, _save_position
from src.interfaces.telegram_guard import _check_cooldown, guard
from src.interfaces.telegram_helpers import (
    _chunk_text,
    _find_excluded_tickers,
    get_portfolio_positions,
    html_escape,
)
from src.portfolio.allocator import allocator
from src.reports import generate_portfolio_csv

logger = structlog.get_logger(__name__)


@guard(with_cooldown=True)
async def allocate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        db = get_session()
        try:
            rows = get_portfolio_positions(db)
            portfolio_total = sum(r["value"] for r in rows)
        finally:
            db.close()
        if portfolio_total and portfolio_total >= 500:
            amount = portfolio_total
            await _reply_with_allocation(update, amount, exclude=set())
            return
        await update.effective_message.reply_text("Укажите сумму: /allocate 100000")
        return
    try:
        full_text = " ".join(context.args)
        amount = float(context.args[0].replace(" ", "").replace(",", "."))
        if amount < 500:
            await update.effective_message.reply_text("Минимальная сумма — 500 ₽")
            return
        exclude = _find_excluded_tickers(full_text)
        await _reply_with_allocation(update, amount, exclude=exclude)
    except ValueError:
        await update.effective_message.reply_text("Укажите число: /allocate 100000")


@guard(with_cooldown=True)
async def stress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    amount = None
    if context.args:
        with contextlib.suppress(ValueError):
            amount = float(context.args[0].replace(" ", "").replace(",", "."))

    if amount:
        await update.effective_message.reply_text(f"🔬 Рассчитываю сценарии для {amount:,.0f} ₽...")
        picks = await allocator.recommend(capital=amount)
        plan = {"recommendation": {"items": picks}}
        positions = format_portfolio_for_stress(plan)
    else:
        await update.effective_message.reply_text("🔬 Анализирую текущий портфель...")
        db = get_session()
        try:
            rows = get_portfolio_positions(db)
            positions = [
                {
                    "ticker": r["ticker"],
                    "amount": r["value"],
                    "last_price": r["current_price"],
                    "sector": r["sector"],
                    "name": r["name"] or r["ticker"],
                }
                for r in rows
                if r["value"] > 0
            ]
        finally:
            db.close()

    if not positions:
        await update.effective_message.reply_text("Нет позиций для тестирования. Добавьте портфель или укажите сумму.")
        return

    tester = StressTester(positions)

    crash_results = tester.run_crash_scenarios()
    sector_results = tester.run_sector_shocks()

    text = "🧪 <b>Стресс-тест портфеля</b>\n\n"
    text += f"Сумма: {tester.total:,.0f} ₽\n\n"
    text += "<b>Кризисные сценарии:</b>\n"
    text += tester.format_results(crash_results)
    text += "<b>Секторальные шоки:</b>\n"
    text += tester.format_results(sector_results)

    for chunk in _chunk_text(text, 4096):
        await update.effective_message.reply_text(chunk, parse_mode="HTML")


@guard(with_cooldown=True)
async def export_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_session()
    try:
        rows = get_portfolio_positions(db)
        if not rows:
            await update.effective_message.reply_text("Портфель пуст. Добавьте позиции через /add SBER 10")
            return

        csv_content = generate_portfolio_csv(rows)
        await update.effective_message.reply_document(
            document=io.BytesIO(csv_content.encode("utf-8-sig")),
            filename="portfolio.csv",
            caption="\U0001f4ca Отчёт по портфелю",
        )
    finally:
        db.close()


@guard()
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_cooldown(update):
        return

    msg = await update.effective_message.reply_text("⏳ Синхронизация с T-Bank...")
    sync_errors: list[str] = []
    try:
        from src.trading.brokers.sync import sync_portfolio_from_broker

        sync_result = await sync_portfolio_from_broker(user_id=1)
        if sync_result.get("status") == "no_token":
            await msg.edit_text("❌ TINKOFF_TOKEN не настроен")
            return
        if sync_result.get("status") == "no_accounts":
            await msg.edit_text("❌ Нет счетов в T-Bank")
            return
        sync_errors = [e for e in cast(list[Any], sync_result.get("errors", [])) if e]
    except Exception as e:
        logger.warning("Sync failed: %s", e)
        sync_errors = [str(e)]

    db = get_session()
    try:
        rows = get_portfolio_positions(db)
        if not rows:
            try:
                from src.trading.brokers.tbank import TBankClient

                async with TBankClient(use_sandbox=settings.tinkoff_sandbox) as tbank:
                    accounts = await tbank.get_accounts()
                    if accounts:
                        balance = await tbank.get_account_balance(str(cast(dict[str, Any], accounts[0])["id"]))
                        await msg.edit_text(
                            f"📭 <b>Портфель пуст</b>\n\n"
                            f"💵 Доступно: {balance:,.0f} ₽\n\n"
                            f"Сигналы пока не дают BUY/SELL.\n"
                            f"Текущие сигналы: <code>/portfolio</code> (обновляется раз в час)",
                            parse_mode="HTML",
                        )
                        return
                await msg.edit_text("📭 Портфель пуст. Нет счетов в T-Bank.")
                return
            except Exception as e:
                logger.warning("Failed to get balance: %s", e)
                await msg.edit_text("📭 Портфель пуст. Нет позиций.")
                return

        lines = ["📊 <b>Портфель (T-Bank)</b>\n"]
        if sync_errors:
            lines.append("⚠️ <b>Ошибки синка:</b>\n")
            for err in sync_errors[:3]:
                lines.append(f"• {html_escape(err[:120])}")
            lines.append("")
        total_value = 0.0
        total_cost = 0.0
        total_clean_value = 0.0
        for r in rows:
            qty = r["quantity"]
            avg = r["avg_price"]
            cur = r["current_price"]
            val = r["value"]
            clean_price = r.get("clean_price", cur)
            clean_val = clean_price * qty
            cost = avg * qty
            pnl = clean_val - cost
            pnl_pct = ((clean_price / avg) - 1) * 100 if avg > 0 else 0.0
            emoji = "🟢" if pnl > 0.5 else ("🔴" if pnl < -0.5 else "⚪")
            pnl_display = "" if abs(pnl) < 0.5 else f"{pnl:+,.2f}"
            pnl_pct_display = "" if abs(pnl_pct) < 0.01 else f"{pnl_pct:+.2f}%"
            pnl_line = f"   P&L: {pnl_display} ₽ ({pnl_pct_display})" if pnl_display and pnl_pct_display else "   P&L: ~0 ₽"

            lines.append(
                f"{emoji} <b>{html_escape(r['ticker'])}</b>: {qty:.0f} шт × {cur:.2f} ₽\n   Средняя: {avg:.2f} | Стоимость: {val:,.0f} ₽\n{pnl_line}"
            )
            total_value += val
            total_cost += cost
            total_clean_value += clean_val

        total_pnl = total_clean_value - total_cost
        total_pnl_pct = ((total_clean_value / total_cost) - 1) * 100 if total_cost > 0 else 0.0
        total_emoji = "🟢" if total_pnl > 0.5 else ("🔴" if total_pnl < -0.5 else "⚪")
        total_pnl_str = "" if abs(total_pnl) < 0.5 else f"{total_pnl:+,.2f}"
        total_pnl_pct_str = "" if abs(total_pnl_pct) < 0.01 else f"{total_pnl_pct:+.2f}%"
        pnl_suffix = f" | P&L: {total_pnl_str} ₽ ({total_pnl_pct_str})" if total_pnl_str and total_pnl_pct_str else " | P&L: ~0 ₽"
        lines.append(f"\n{total_emoji} <b>Итого:</b> {total_value:,.0f} ₽{pnl_suffix}")
        await msg.edit_text("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()


@guard(with_cooldown=True)
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Использование: /add TICKER КОЛИЧЕСТВО [ЦЕНА]\n"
            "Например: /add SBER 10 250\n"
            "Цена опциональна (будет определена автоматически)"
        )
        return
    ticker = args[0].upper()
    try:
        qty = float(args[1].replace(",", "."))
    except ValueError:
        await update.effective_message.reply_text("Количество должно быть числом.")
        return
    avg_price = None
    if len(args) >= 3:
        try:
            avg_price = float(args[2].replace(",", "."))
        except ValueError:
            await update.effective_message.reply_text("Цена должна быть числом.")
            return
    await _save_position(update, ticker, qty, avg_price)


async def remove_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.effective_message.reply_text("Укажите тикер: /remove SBER")
        return
    ticker = args[0].upper()
    qty = None
    if len(args) >= 2:
        with contextlib.suppress(ValueError):
            qty = float(args[1].replace(",", "."))

    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            await update.effective_message.reply_text(f"Инструмент {ticker} не найден")
            return
        existing = db.query(PortModel).filter_by(instrument_id=inst.id).first()
        if not existing:
            await update.effective_message.reply_text(f"{ticker} нет в портфеле")
            return
        if qty and qty < existing.quantity:
            existing.quantity -= qty
            db.commit()
            await update.effective_message.reply_text(f"✅ {ticker}: продано {qty} шт. (осталось {existing.quantity:.1f} шт.)")
        else:
            db.delete(existing)
            db.commit()
            await update.effective_message.reply_text(f"✅ {ticker}: полностью удалён из портфеля")
    except Exception:
        logger.exception("Unhandled exception")
        db.rollback()
        logger.warning("Remove position error", exc_info=True)
        await update.effective_message.reply_text("❌ Не удалось удалить позицию. Попробуйте позже.")
    finally:
        db.close()


@guard(with_cooldown=True)
async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.trading.execution.audit import get_trade_history
    from src.trading.risk.guards import get_day_pnl

    pnl, pnl_pct = get_day_pnl()
    trades = get_trade_history(limit=10)
    text = "📊 <b>P&L</b>\n\n"
    text += f"Сегодня: {pnl:+,.0f} ₽ ({pnl_pct:+.2%})\n\n"
    if trades:
        text += "<b>Последние сделки:</b>\n"
        for t in trades[:5]:
            t_pnl_val: Optional[float] = cast(Optional[float], t.get("pnl"))
            emoji = "🟢" if t_pnl_val is not None and t_pnl_val >= 0 else "🔴"
            text += f"{emoji} {html_escape(t['ticker'])} {t['direction']} {t['quantity']}шт @ {t['price']:.2f}"
            if t_pnl_val is not None:
                text += f" ({t_pnl_val:+.0f} ₽)"
            text += "\n"
    if not trades:
        text += "Сделок пока нет."
    for chunk in _chunk_text(text, 4096):
        await update.effective_message.reply_text(chunk, parse_mode="HTML")


@guard(with_cooldown=True)
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.effective_message.reply_text("📄 Генерирую отчёт...")
    try:
        from src.reports.weekly_pdf import generate_weekly_report

        png_bytes = generate_weekly_report()
        if png_bytes is None:
            await msg.edit_text("❌ Не удалось сформировать отчёт. Нужно больше данных.")
            return
        await msg.delete()
        await update.effective_message.reply_photo(
            photo=png_bytes,
            caption="📊 Отчёт за 120 дней",
        )
    except Exception:
        logger.exception("Unhandled exception")
        logger.warning("Report error", exc_info=True)
        await msg.edit_text("❌ Ошибка формирования отчёта.")
