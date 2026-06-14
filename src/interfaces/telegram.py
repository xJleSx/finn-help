import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.cli import run_analysis
from src.config import settings

logger = logging.getLogger(__name__)

ACTION_EMOJI = {
    "BUY": "\U0001F7E2",
    "CAUTIOUS_BUY": "\U0001F7E1",
    "HOLD": "\u26AA",
    "SELL": "\U0001F534",
    "NEUTRAL": "\u26AA",
}

subscribers: set[int] = set()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001F916 FinAdvisor — финансовый ассистент\n\n"
        "Команды:\n"
        "/analyze TICKER — анализ инструмента\n"
        "/portfolio — портфель\n"
        "/rates — курсы валют\n"
        "/geo — геополитический риск\n"
        "/subscribe — подписаться на уведомления\n"
        "/unsubscribe — отписаться\n"
        "/daily — ежедневная сводка\n"
        "/help — справка"
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    subscribers.add(uid)
    await update.message.reply_text("\u2705 Вы подписаны на уведомления о новых сигналах")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    subscribers.discard(uid)
    await update.message.reply_text("\u274c Подписка отменена")


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.notifications.service import NotificationService, format_daily_summary_text

    ns = NotificationService()
    summary = ns.get_daily_summary()
    text = format_daily_summary_text(summary)
    await update.message.reply_markdown(text)


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите тикер: /analyze SBER")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"\U0001F50D Анализирую {ticker}...")

    try:
        fused, advice = await run_analysis(ticker, with_llm=True)
        if not fused:
            await update.message.reply_text(f"\u274C {advice}")
            return
        emoji = ACTION_EMOJI.get(fused["action"], "\u26AA")
        text = f"{emoji} *{ticker}* — {fused['action']} (уверенность: {fused['confidence']:.0%})\n"
        for r in fused.get("reasons", []):
            text += f"\u2022 {r}\n"
        if advice:
            text += f"\n{advice}"
        text += f"\n\U0001F4A1 Доля: до {fused['max_portfolio_pct']}% портфеля"
        await update.message.reply_markdown(text)
    except Exception as e:
        await update.message.reply_text(f"\u274C Ошибка: {e}")


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.connection import get_session
    from src.db.models import Instrument, Portfolio, Price

    db = get_session()
    try:
        positions = db.query(Portfolio).all()
        if not positions:
            await update.message.reply_text("Портфель пуст")
            return

        lines = ["\U0001F4CA Портфель:\n"]
        total = 0
        for p in positions:
            inst = db.query(Instrument).filter_by(id=p.instrument_id).first()
            price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
            current = price.close if price else 0
            value = current * p.quantity if current else 0
            profit = ((current / p.avg_price) - 1) * 100 if current and p.avg_price else 0
            emoji = "\U0001F7E2" if profit > 0 else "\U0001F534"
            lines.append(f"{emoji} {inst.ticker if inst else '?'}: {p.quantity:.1f} \u00d7 {current:.2f} = {value:.2f}\u20bd ({profit:+.1f}%)")
            total += value

        lines.append(f"\n\U0001F4B5 Всего: {total:.2f} \u20bd")
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.collectors.cbr import CBRCollector

    cbr = CBRCollector()
    try:
        rates = await cbr.get_rates()
        majors = ["USD", "EUR", "CNY", "GBP", "KZT", "TRY"]
        lines = ["\U0001F3E6 Курсы ЦБ РФ:\n"]
        for r in rates:
            if r["code"] in majors:
                lines.append(f"  {r['code']}: {r['value']:.2f} \u20bd")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"\u274C Ошибка: {e}")


async def geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.connection import get_session
    from src.db.models import GeoRiskScore

    db = get_session()
    try:
        score = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        if score:
            level = "\u26A1\uFE0F КРИТИЧЕСКИЙ" if score.score > 7 else "\u26A1 ВЫСОКИЙ" if score.score > 5 else "\U0001F7E1 УМЕРЕННЫЙ" if score.score > 3 else "\U0001F7E2 НИЗКИЙ"
            await update.message.reply_text(
                f"\U0001F30D Геополитический риск: {score.score}/10 ({level})\n"
                f"Дата: {score.date}"
            )
        else:
            await update.message.reply_text("Нет данных. Запустите daily update.")
    finally:
        db.close()


async def broadcast_signal(n):
    if not subscribers:
        return
    from src.notifications.service import format_signal_text
    text = format_signal_text(n)
    for uid in subscribers:
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Failed to send to {uid}: {e}")


async def broadcast_daily_summary():
    if not subscribers:
        return
    from src.notifications.service import NotificationService, format_daily_summary_text
    ns = NotificationService()
    summary = ns.get_daily_summary()
    text = format_daily_summary_text(summary)
    for uid in subscribers:
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Failed to send daily to {uid}: {e}")


app: Optional[Application] = None


async def run_bot():
    global app
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set in .env")
        return

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("rates", rates))
    app.add_handler(CommandHandler("geo", geo))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("daily", daily))

    logger.info("Bot started polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(60)
