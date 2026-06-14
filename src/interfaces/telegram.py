import asyncio
import logging
import re
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.cli import run_analysis
from src.config import settings
from src.db.connection import get_session
from src.db.models import Instrument

logger = logging.getLogger(__name__)

ACTION_EMOJI = {
    "BUY": "\U0001f7e2",
    "CAUTIOUS_BUY": "\U0001f7e1",
    "HOLD": "\u26aa",
    "SELL": "\U0001f534",
    "NEUTRAL": "\u26aa",
}

RUSSIAN_NAMES: dict[str, str] = {
    "сбер": "SBER", "сбера": "SBER", "сбербанк": "SBER",
    "газпром": "GAZP", "газпрома": "GAZP",
    "лукойл": "LKOH", "лукойла": "LKOH",
    "втб": "VTBR",
    "яндекс": "YNDX", "yandex": "YNDX",
    "нлмк": "NLMK",
    "магнит": "MGNT", "магнита": "MGNT",
    "мтс": "MTSS",
    "татнефть": "TATN", "татнефти": "TATN",
    "ростелеком": "RTKM",
    "фосагро": "PHOR",
    "афк система": "AFKS", "система": "AFKS",
    "аэрофлот": "AFLT",
    "роснефть": "ROSN", "роснефти": "ROSN",
    "норникель": "GMKN", "норильский никель": "GMKN",
    "полюс": "PLZL",
    "алроса": "ALRS",
    "северсталь": "CHMF",
    "магнитогорский": "MAGN",
    "интер рао": "IRAO",
    "ozon": "OZON",
    "тинькофф": "TCSG", "ткс": "TCSG", "tcsg": "TCSG",
    "озон": "OZON",
    "московская биржа": "MOEX", "биржа": "MOEX", "moex": "MOEX",
    "распадская": "RASP",
    "транснефть": "TRNFP",
    "преф сбер": "SBERP",
    "преф татнефть": "TATNP",
    "преф": "SNGSP",
    "самараэнерго": "SMLT",
    "юнипро": "UPRO",
    "всм": "VSMO", "всмпо": "VSMO",
    "полиметалл": "POLY",
    "русал": "RUAL",
    "пик": "PIKK", "пикк": "PIKK",
    "лср": "LSRG", "лсрг": "LSRG",
    "мосэнерго": "MSNG",
    "фск": "FEES", "федеральная сетевая": "FEES",
    "русгидро": "HYDR", "гидро": "HYDR",
    "башнефть": "BANE",
    "преф башнефть": "BANEP",
    "селенга": "SELG",
    "трубная": "TRNR",
    "five": "FIVE", "пятерочка": "FIVE", "x5": "FIVE", "икс5": "FIVE",
    "fix": "FIX", "фикс": "FIX",
}

subscribers: set[int] = set()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001f916 FinAdvisor — финансовый ассистент\n\n"
        "Просто напишите вопрос про акцию:\n"
        "• «анализ сбер»\n"
        "• «что с газпромом?»\n"
        "• «дивиденды лукойла»\n"
        "• «куда вложить 50000»\n"
        "• или /analyze SBER\n\n"
        "Команды:\n"
        "/analyze TICKER — анализ инструмента\n"
        "/ask вопрос — совет в свободной форме\n"
        "/allocate СУММА — распределение капитала\n"
        "/portfolio — портфель\n"
        "/rates — курсы валют\n"
        "/geo — геополитический риск\n"
        "/subscribe — подписаться на уведомления\n"
        "/unsubscribe — отписаться\n"
        "/daily — ежедневная сводка"
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


async def allocate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите сумму: /allocate 100000")
        return
    try:
        amount = float(context.args[0].replace(" ", "").replace(",", "."))
        if amount < 500:
            await update.message.reply_text("Минимальная сумма — 500 ₽")
            return
        await _reply_with_allocation(update, amount)
    except ValueError:
        await update.message.reply_text("Укажите число: /allocate 100000")


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
    await _handle_text(update, text)


async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    amount = _extract_allocation_amount(text)
    if amount is not None:
        await _reply_with_allocation(update, amount)
    else:
        tickers = _find_tickers(text)
        if tickers:
            ticker = tickers[0]
            if len(tickers) > 1:
                await update.message.reply_text(f"Нашёл несколько, анализирую {ticker}")
            await _reply_with_analysis(update, ticker)
        else:
            await update.message.reply_text(
                "Не нашёл тикер в вашем сообщении.\n"
                "Попробуйте:\n"
                "• «анализ сбер»\n"
                "• «куда вложить 50000»\n"
                "• «распредели 100000 рублей»\n"
                "• /allocate 100000"
            )


async def _handle_text(update: Update, text: str):
    amount = _extract_allocation_amount(text)
    if amount is not None:
        await _reply_with_allocation(update, amount)
        return

    tickers = _find_tickers(text)
    if tickers:
        ticker = tickers[0]
        if len(tickers) > 1:
            await update.message.reply_text(f"Нашёл несколько, анализирую {ticker}")
        await _reply_with_analysis(update, ticker)
    else:
        await update.message.reply_text(
            "Не нашёл тикер в вашем сообщении.\n"
            "Попробуйте:\n"
            "• «анализ сбер»\n"
            "• «куда вложить 50000»\n"
            "• «распредели 100000 рублей»"
        )


async def _reply_with_analysis(update: Update, ticker: str):
    await update.message.reply_text(f"\U0001f50d Анализирую {ticker}...")

    try:
        fused, advice = await run_analysis(ticker, with_llm=True)
        if not fused:
            await update.message.reply_text(f"\u274c {advice}")
            return

        action = fused["action"]
        confidence = fused["confidence"]
        emoji = ACTION_EMOJI.get(action, "\u26aa")

        action_labels = {"BUY": "рекомендуется к покупке", "CAUTIOUS_BUY": "можно рассмотреть для покупки",
                         "HOLD": "рекомендуется держать", "SELL": "рекомендуется продать", "NEUTRAL": "нейтрально"}
        label = action_labels.get(action, action)

        text = f"{emoji} *{ticker}* — {label}\n"
        text += f"Уверенность: {confidence:.0%}\n"
        text += "\n" + _simplify_reasons(fused.get("reasons", []))

        if advice:
            text += f"\n\n{advice}"
        text += f"\n\n\U0001f4a1 Рекомендуемая доля в портфеле: до {fused['max_portfolio_pct']}%"

        for chunk in _chunk_text(text, 4096):
            await update.message.reply_markdown(chunk)
    except Exception as e:
        logger.warning("Analysis error", exc_info=True)
        await update.message.reply_text(
            f"\u274c Ошибка: {e}\nУбедитесь, что запущен `finn update` и данные загружены."
        )


def _extract_allocation_amount(text: str) -> float | None:
    text_lower = text.lower().strip()
    alloc_keywords = ["вложить", "инвестировать", "распредели", "распределение",
                      "allocate", "разложить", "разместить"]
    if not any(k in text_lower for k in alloc_keywords):
        return None
    numbers = re.findall(r"(\d[\d\s]*\d|\d)", text_lower.replace(",", ".").replace(" ", ""))
    if numbers:
        return float(numbers[-1])
    return None


async def _reply_with_allocation(update: Update, capital: float):
    await update.message.reply_text(f"\U0001f50d Распределяю {capital:,.0f} ₽...")

    try:
        from src.portfolio.allocator import allocator

        plan = allocator.allocate(capital)
        if not plan or not plan.get("plan"):
            await update.message.reply_text("Не удалось составить план. Запустите `finn update` для загрузки данных.")
            return

        text = f"\U0001f4b0 Распределение {capital:,.0f} ₽\n\n"
        for cat, data in plan["plan"].items():
            text += f"*{data['label']}* — {data['budget']:,.0f} ₽\n"
            for item in data.get("items", []):
                name = item.get("name") or item["ticker"]
                shares_info = ""
                risk = item.get("risk", {})
                if risk.get("suggested_shares", 0) > 0:
                    shares_info = f" ≈ {risk['suggested_shares']} шт."
                text += f"  \u2022 *{item['ticker']}* ({name}): {item['amount']:,.0f} ₽{shares_info}\n"
                if item.get("reason"):
                    text += f"    ({item['reason']})\n"
            text += "\n"

        total = plan.get("total_allocated", 0)
        text += f"\U0001f4b5 *Итого распределено:* {total:,.0f} ₽"
        reserve = plan.get("reserve", 0)
        if reserve > 0:
            text += f"\n\U0001f4a4 *Резерв:* {reserve:,.0f} ₽"

        monthly = plan.get("projected_monthly_yield", 0)
        if monthly > 0:
            pct = plan.get("projected_monthly_pct", 0)
            text += f"\n\U0001f4c8 *Прогноз доходности:* {monthly:,.0f} ₽/мес ({pct:.1f}%)"

        for chunk in _chunk_text(text, 4096):
            await update.message.reply_markdown(chunk)
    except Exception as e:
        logger.warning("Allocation error", exc_info=True)
        await update.message.reply_text(f"\u274c Ошибка: {e}. Убедитесь, что запущен `finn update`.")


def _simplify_reasons(reasons: list[str]) -> str:
    if not reasons:
        return ""

    simple = []
    for r in reasons:
        r_lower = r.lower()

        if "RSI" in r:
            if "перепроданность" in r_lower:
                simple.append("📉 Акция недооценена — потенциальный разворот вверх")
            elif "перекупленность" in r_lower:
                simple.append("📈 Акция переоценена — возможна коррекция")
            else:
                simple.append("📊 Нейтральный баланс спроса и предложения")
        elif "macd" in r_lower:
            if "положитель" in r_lower:
                simple.append("🟢 Краткосрочный тренд восходящий")
            elif "отрицатель" in r_lower:
                simple.append("🔴 Краткосрочный тренд нисходящий")
        elif "цена ниже" in r_lower:
            simple.append("📉 Цена ниже средних значений — потенциальная зона для покупки")
        elif "цена выше" in r_lower:
            simple.append("📈 Цена выше средних значений — позитивный сигнал")
        elif "bollinger" in r_lower:
            if "отскок" in r_lower:
                simple.append("🎯 Цена у нижней границы — возможен отскок вверх")
            elif "коррекция" in r_lower:
                simple.append("⚠️ Цена у верхней границы — возможна коррекция вниз")
        elif "волатильность" in r_lower:
            if "high" in r_lower:
                simple.append("🌊 Высокая волатильность — повышенный риск")
            elif "low" in r_lower:
                simple.append("🌊 Низкая волатильность — рынок спокоен")
            else:
                simple.append("🌊 Нормальная волатильность")
        elif "risk:" in r_lower or "sharpe" in r_lower:
            continue
        elif "ml-прогноз" in r_lower or "ml" in r_lower:
            if "+" in r:
                simple.append("🤖 Прогноз модели: умеренный рост")
            elif "-" in r:
                simple.append("🤖 Прогноз модели: возможное снижение")
            else:
                simple.append("🤖 Прогноз модели: без изменений")
        elif "аномалии" in r_lower:
            simple.append("⚠️ Обнаружены аномалии в фундаментальных показателях")
        elif "геополитический" in r_lower:
            simple.append("🌍 Повышенные геополитические риски")
        elif "news" in r_lower or "новости" in r_lower:
            if "позитив" in r_lower or ">" in r:
                simple.append("📰 Новости положительные")
            elif "негатив" in r_lower:
                simple.append("📰 Новости негативные")
        elif "макро:" in r_lower or "brent" in r_lower or "ключевая" in r_lower:
            simple.append("🏛️ Макроэкономическая ситуация учитывается")

    if not simple:
        simple.append("↔️ Нейтральный сигнал")

    return "\n".join("• " + s for s in simple[:4])


def _find_tickers(text: str) -> list[str]:
    text_lower = text.lower().strip()

    matched = re.findall(r"([а-яёa-z]+)", text_lower)
    for word in matched:
        if word in RUSSIAN_NAMES:
            return [RUSSIAN_NAMES[word]]

    for phrase, ticker in RUSSIAN_NAMES.items():
        if phrase in text_lower:
            return [ticker]

    try:
        db = get_session()
        try:
            instruments = db.query(Instrument.ticker).all()
            db_tickers = {r[0] for r in instruments}
        finally:
            db.close()
    except Exception:
        db_tickers = set()

    words = re.findall(r"[A-Za-z0-9]{2,}", text.upper())
    found = [w for w in words if w in db_tickers or w in RUSSIAN_NAMES.values()]
    if found:
        return found

    return []


def _chunk_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    return [text[i:i + max_len] for i in range(0, len(text), max_len)]


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.models import Portfolio as PortModel
    from src.db.models import Price

    db = get_session()
    try:
        positions = db.query(PortModel).all()
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
    for uid in list(subscribers):
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
    for uid in list(subscribers):
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
    app.add_handler(CommandHandler("allocate", allocate))
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
