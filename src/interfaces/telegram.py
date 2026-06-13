import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.config import settings
from src.cli import run_analysis

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 FinAdvisor — финансовый ассистент\n\n"
        "Команды:\n"
        "/analyze TICKER — анализ инструмента\n"
        "/portfolio — портфель\n"
        "/rates — курсы валют\n"
        "/geo — геополитический риск\n"
        "/help — справка"
    )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите тикер: /analyze SBER")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"🔍 Анализирую {ticker}...")

    try:
        fused, advice = await run_analysis(ticker, with_llm=True)
        if not fused:
            await update.message.reply_text(f"❌ {advice}")
            return
        text = f"📊 {ticker} — {fused['action']} (уверенность: {fused['confidence']:.0%})\n"
        for r in fused.get("reasons", []):
            text += f"• {r}\n"
        if advice:
            text += f"\n{advice}"
        text += f"\n💡 Доля: до {fused['max_portfolio_pct']}% портфеля"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.connection import get_session
    from src.db.models import Portfolio, Instrument, Price

    db = get_session()
    try:
        positions = db.query(Portfolio).all()
        if not positions:
            await update.message.reply_text("Портфель пуст")
            return

        lines = ["📊 Портфель:\n"]
        total = 0
        for p in positions:
            inst = db.query(Instrument).filter_by(id=p.instrument_id).first()
            price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
            current = price.close if price else 0
            value = current * p.quantity if current else 0
            profit = ((current / p.avg_price) - 1) * 100 if current and p.avg_price else 0
            emoji = "🟢" if profit > 0 else "🔴"
            lines.append(f"{emoji} {inst.ticker if inst else '?'}: {p.quantity:.1f} × {current:.2f} = {value:.2f}₽ ({profit:+.1f}%)")
            total += value

        lines.append(f"\n💵 Всего: {total:.2f} ₽")
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.collectors.cbr import CBRCollector

    cbr = CBRCollector()
    try:
        rates = await cbr.get_rates()
        majors = ["USD", "EUR", "CNY", "GBP", "KZT", "TRY"]
        lines = ["🏦 Курсы ЦБ РФ:\n"]
        for r in rates:
            if r["code"] in majors:
                lines.append(f"  {r['code']}: {r['value']:.2f} ₽")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.connection import get_session
    from src.db.models import GeoRiskScore

    db = get_session()
    try:
        score = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        if score:
            level = "КРИТИЧЕСКИЙ" if score.score > 7 else "ВЫСОКИЙ" if score.score > 5 else "УМЕРЕННЫЙ" if score.score > 3 else "НИЗКИЙ"
            await update.message.reply_text(
                f"🌍 Геополитический риск: {score.score}/10 ({level})\n"
                f"Дата: {score.date}"
            )
        else:
            await update.message.reply_text("Нет данных. Запустите daily update.")
    finally:
        db.close()


async def run_bot():
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

    logger.info("Bot started polling...")
    await app.run_polling()
