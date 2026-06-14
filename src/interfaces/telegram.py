import asyncio
import logging
import re
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.cli import run_analysis
from src.config import settings

logger = logging.getLogger(__name__)

ACTION_EMOJI = {
    "BUY": "\U0001f7e2",
    "CAUTIOUS_BUY": "\U0001f7e1",
    "HOLD": "\u26aa",
    "SELL": "\U0001f534",
    "NEUTRAL": "\u26aa",
}

subscribers: set[int] = set()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001f916 FinAdvisor — финансовый ассистент\n\n"
        "Просто напишите название тикера (SBER, GAZP, LKOH...)\n"
        "или задайте вопрос в свободной форме.\n\n"
        "Команды:\n"
        "/analyze TICKER — анализ инструмента\n"
        "/ask вопрос — совет по инструменту\n"
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
    await _reply_with_analysis(update, ticker)


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Задайте вопрос, например: /ask Что думаешь про SBER?")
        return
    await _handle_chat(update, text)


async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    await _handle_chat(update, text)


async def _handle_chat(update: Update, text: str):
    tickers = _extract_tickers(text)
    if not tickers:
        await update.message.reply_text(
            "Я не нашёл тикер в вашем сообщении.\n"
            "Напишите название акции (SBER, GAZP, LKOH, YNDX...)\n"
            "или используйте /analyze TICKER."
        )
        return

    if len(tickers) > 1:
        ticker = tickers[0]
        await update.message.reply_text(f"Нашёл несколько тикеров, анализирую {ticker}")
    else:
        ticker = tickers[0]

    await _reply_with_analysis(update, ticker)


async def _reply_with_analysis(update: Update, ticker: str):
    await update.message.reply_text(f"\U0001f50d Анализирую {ticker}...")

    try:
        fused, advice = await run_analysis(ticker, with_llm=True)
        if not fused:
            await update.message.reply_text(f"\u274c {advice}")
            return

        emoji = ACTION_EMOJI.get(fused["action"], "\u26aa")
        text = f"{emoji} *{ticker}* — {fused['action']} (уверенность: {fused['confidence']:.0%})\n"
        for r in fused.get("reasons", []):
            text += f"\u2022 {r}\n"

        if advice:
            text += f"\n{advice}"
        text += f"\n\U0001f4a1 Доля: до {fused['max_portfolio_pct']}% портфеля"

        for chunk in _chunk_text(text, 4096):
            await update.message.reply_markdown(chunk)
    except Exception as e:
        logger.warning("Analysis error", exc_info=True)
        await update.message.reply_text(f"\u274c Ошибка: {e}. Попробуйте /analyze {ticker}")


def _extract_tickers(text: str) -> list[str]:
    known = {"SBER", "GAZP", "LKOH", "VTBR", "MOEX", "YNDX", "NLMK", "MGNT", "MTSS",
             "SNGS", "TATN", "RTKM", "PHOR", "AFKS", "AFLT", "ROSN", "GMKN", "PLZL",
             "ALRS", "CHMF", "MAGN", "IRAO", "SMLT", "FIVE", "OZON", "QIWI", "TCSG",
             "SBERP", "SNGSP", "RASP", "TRNFP", "BANE", "BANEP", "FEES", "HYDR",
             "LSRG", "MSNG", "PIKK", "POLY", "RUAL", "RTKMP", "SELG", "TATNP",
             "UPRO", "VSMO", "MOSP", "SGZH",
             "FXRL", "SBMX", "TMOS", "AKIM", "RUSB", "TRUR",
             "SU26238RMFS5", "SU26243RMFS2", "SU26248RMFS1"}

    words = re.findall(r"[A-Za-z0-9]{2,}", text.upper())
    found = [w for w in words if w in known]
    return found


def _chunk_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    for i in range(0, len(text), max_len):
        chunks.append(text[i:i + max_len])
    return chunks


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.connection import get_session
    from src.db.models import Instrument, Portfolio, Price

    db = get_session()
    try:
        positions = db.query(Portfolio).all()
        if not positions:
            await update.message.reply_text("Портфель пуст")
            return

        lines = ["\U0001f4ca Портфель:\n"]
        total = 0
        for p in positions:
            inst = db.query(Instrument).filter_by(id=p.instrument_id).first()
            price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
            current = price.close if price else 0
            value = current * p.quantity if current else 0
            profit = ((current / p.avg_price) - 1) * 100 if current and p.avg_price else 0
            emoji = "\U0001f7e2" if profit > 0 else "\U0001f534"
            lines.append(
                f"{emoji} {inst.ticker if inst else '?'}: {p.quantity:.1f} \u00d7 {current:.2f}"
                f" = {value:.2f}\u20bd ({profit:+.1f}%)"
            )
            total += value

        lines.append(f"\n\U0001f4b5 Всего: {total:.2f} \u20bd")
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.collectors.cbr import CBRCollector

    cbr = CBRCollector()
    try:
        rates = await cbr.get_rates()
        majors = ["USD", "EUR", "CNY", "GBP", "KZT", "TRY"]
        lines = ["\U0001f3e6 Курсы ЦБ РФ:\n"]
        for r in rates:
            if r["code"] in majors:
                lines.append(f"  {r['code']}: {r['value']:.2f} \u20bd")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"\u274c Ошибка: {e}")


async def geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.connection import get_session
    from src.db.models import GeoRiskScore

    db = get_session()
    try:
        score = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        if score:
            level = (
                "\u26a1\ufe0f КРИТИЧЕСКИЙ"
                if score.score > 7
                else "\u26a1 ВЫСОКИЙ"
                if score.score > 5
                else "\U0001f7e1 УМЕРЕННЫЙ"
                if score.score > 3
                else "\U0001f7e2 НИЗКИЙ"
            )
            await update.message.reply_text(
                f"\U0001f30d Геополитический риск: {score.score}/10 ({level})\nДата: {score.date}"
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
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("rates", rates))
    app.add_handler(CommandHandler("geo", geo))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("daily", daily))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    logger.info("Bot started polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())
