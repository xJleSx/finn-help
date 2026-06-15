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
    "сбер": "SBER",
    "сбера": "SBER",
    "сбербанк": "SBER",
    "газпром": "GAZP",
    "газпрома": "GAZP",
    "лукойл": "LKOH",
    "лукойла": "LKOH",
    "втб": "VTBR",
    "яндекс": "YNDX",
    "yandex": "YNDX",
    "нлмк": "NLMK",
    "магнит": "MGNT",
    "магнита": "MGNT",
    "мтс": "MTSS",
    "татнефть": "TATN",
    "татнефти": "TATN",
    "ростелеком": "RTKM",
    "фосагро": "PHOR",
    "афк система": "AFKS",
    "система": "AFKS",
    "аэрофлот": "AFLT",
    "роснефть": "ROSN",
    "роснефти": "ROSN",
    "норникель": "GMKN",
    "норильский никель": "GMKN",
    "полюс": "PLZL",
    "алроса": "ALRS",
    "северсталь": "CHMF",
    "магнитогорский": "MAGN",
    "интер рао": "IRAO",
    "ozon": "OZON",
    "тинькофф": "TCSG",
    "ткс": "TCSG",
    "tcsg": "TCSG",
    "озон": "OZON",
    "московская биржа": "MOEX",
    "биржа": "MOEX",
    "moex": "MOEX",
    "распадская": "RASP",
    "транснефть": "TRNFP",
    "преф сбер": "SBERP",
    "преф татнефть": "TATNP",
    "преф": "SNGSP",
    "самараэнерго": "SMLT",
    "юнипро": "UPRO",
    "всм": "VSMO",
    "всмпо": "VSMO",
    "полиметалл": "POLY",
    "русал": "RUAL",
    "пик": "PIKK",
    "пикк": "PIKK",
    "лср": "LSRG",
    "лсрг": "LSRG",
    "мосэнерго": "MSNG",
    "фск": "FEES",
    "федеральная сетевая": "FEES",
    "русгидро": "HYDR",
    "гидро": "HYDR",
    "башнефть": "BANE",
    "преф башнефть": "BANEP",
    "селенга": "SELG",
    "трубная": "TRNR",
    "five": "FIVE",
    "пятерочка": "FIVE",
    "x5": "FIVE",
    "икс5": "FIVE",
    "fix": "FIX",
    "фикс": "FIX",
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
        "/allocate СУММА — куда вложить деньги\n"
        "/portfolio — портфель\n"
        "/rates — курсы валют\n"
        "/geo — геополитический риск\n"
        "/subscribe — подписаться на уведомления\n"
        "/unsubscribe — отписаться\n"
        "/daily — ежедневная сводка\n"
        "/stress — стресс-тест портфеля\n"
        "/stress СУММА — стресс-тест на сумму\n"
        "/backtest — история стратегии\n"
        "/backtest СУММА — бэктест на сумму"
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    ntype = context.args[0] if context.args else "signal"
    if ntype not in ("signal", "daily", "geo", "dividend"):
        ntype = "signal"
    from src.notifications.service import NotificationService

    ns = NotificationService()
    ns.subscribe(uid, cid, ntype)
    type_names = {"signal": "сигналы", "daily": "ежедневные сводки", "geo": "гео-риски", "dividend": "дивиденды"}
    await update.message.reply_text(f"✅ Вы подписаны на {type_names.get(ntype, ntype)}")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ntype = context.args[0] if context.args else None
    from src.notifications.service import NotificationService

    ns = NotificationService()
    ns.unsubscribe(uid, ntype)
    if ntype:
        await update.message.reply_text("❌ Подписка на этот тип уведомлений отменена")
    else:
        await update.message.reply_text("❌ Все подписки отменены")


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
        full_text = " ".join(context.args)
        amount = float(context.args[0].replace(" ", "").replace(",", "."))
        if amount < 500:
            await update.message.reply_text("Минимальная сумма — 500 ₽")
            return
        exclude = _find_excluded_tickers(full_text)
        await _reply_with_allocation(update, amount, exclude=exclude)
    except ValueError:
        await update.message.reply_text("Укажите число: /allocate 100000")


async def stress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.analysis.stress import StressTester, format_portfolio_for_stress
    from src.db.connection import get_session

    amount = None
    if context.args:
        try:
            amount = float(context.args[0].replace(" ", "").replace(",", "."))
        except ValueError:
            pass

    if amount:
        from src.portfolio.allocator import allocator

        await update.message.reply_text(f"🔬 Рассчитываю сценарии для {amount:,.0f} ₽...")
        picks = allocator.recommend(capital=amount)
        plan = {"recommendation": {"items": picks}}
        positions = format_portfolio_for_stress(plan)
    else:
        await update.message.reply_text("🔬 Анализирую текущий портфель...")
        db = get_session()
        try:
            from src.db.models import Instrument, Portfolio, Price

            rows = db.query(Portfolio).all()
            positions = []
            for r in rows:
                inst = db.query(Instrument).filter_by(id=r.instrument_id).first()
                price = (
                    db.query(Price).filter_by(instrument_id=r.instrument_id).order_by(Price.date.desc()).first()
                )
                last_price = price.close if price else 0
                val = last_price * r.quantity if last_price else 0
                if val > 0:
                    positions.append(
                        {
                            "ticker": inst.ticker if inst else "?",
                            "amount": float(val),
                            "last_price": float(last_price) if last_price else 0,
                            "sector": inst.sector or "Прочее",
                            "name": inst.full_name or inst.ticker,
                        }
                    )
        finally:
            db.close()

    if not positions:
        await update.message.reply_text("Нет позиций для тестирования. Добавьте портфель или укажите сумму.")
        return

    tester = StressTester(positions)

    crash_results = tester.run_crash_scenarios()
    sector_results = tester.run_sector_shocks()

    text = "🧪 *Стресс-тест портфеля*\n\n"
    text += f"Сумма: {tester.total:,.0f} ₽\n\n"
    text += "*Кризисные сценарии:*\n"
    text += tester.format_results(crash_results)
    text += "*Секторальные шоки:*\n"
    text += tester.format_results(sector_results)

    for chunk in _chunk_text(text, 4096):
        await update.message.reply_markdown(chunk)


async def backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.analysis.backtest import backtest_allocation

    amount = 100_000
    if context.args:
        try:
            amount = float(context.args[0].replace(" ", "").replace(",", "."))
            if amount < 500:
                await update.message.reply_text("Минимальная сумма — 500 ₽")
                return
        except ValueError:
            pass

    await update.message.reply_text(f"🕰 Прогоняю стратегию для {amount:,.0f} ₽ за последний год...")
    result = backtest_allocation(capital=amount)
    await update.message.reply_markdown(result.summary())


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
        exclude = _find_excluded_tickers(text)
        await _reply_with_allocation(update, amount, exclude=exclude)
        return
    tickers = _find_tickers(text)
    if tickers:
        ticker = tickers[0]
        if len(tickers) > 1:
            await update.message.reply_text(f"Нашёл несколько, анализирую {ticker}")
        await _reply_with_analysis(update, ticker)
        return
    await _ask_llm_general(update, text)


async def _handle_text(update: Update, text: str):
    amount = _extract_allocation_amount(text)
    if amount is not None:
        exclude = _find_excluded_tickers(text)
        await _reply_with_allocation(update, amount, exclude=exclude)
        return

    tickers = _find_tickers(text)
    if tickers:
        ticker = tickers[0]
        if len(tickers) > 1:
            await update.message.reply_text(f"Нашёл несколько, анализирую {ticker}")
        await _reply_with_analysis(update, ticker)
        return

    await _ask_llm_general(update, text)


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

        action_labels = {
            "BUY": "рекомендуется к покупке",
            "CAUTIOUS_BUY": "можно рассмотреть для покупки",
            "HOLD": "рекомендуется держать",
            "SELL": "рекомендуется продать",
            "NEUTRAL": "нейтрально",
        }
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
        await update.message.reply_text(f"\u274c Ошибка: {e}\nУбедитесь, что запущен `finn update` и данные загружены.")


def _find_excluded_tickers(text: str) -> set[str]:
    text_lower = text.lower()
    exclude = set()

    exclude_keywords = ["без ", "кроме ", "недоступ", "не учитывай", "исключ", "убери ",
                        "не рассматривай", "без учета", "без участия", "нет ", "нету ",
                        "отсутств", "не им", "пока нет", "ещё нет", "нет в наличии",
                        "не интересу", "не нужно", "не хочу", "не рассматрива"]

    has_exclusion = any(k in text_lower for k in exclude_keywords)
    if not has_exclusion:
        return exclude

    all_tickers = _find_tickers(text)

    for ticker in all_tickers:
        t_lower = ticker.lower()
        if any(re.search(rf'\b{kw}\s*{re.escape(t_lower)}\b', text_lower) for kw in ["без", "кроме", "нет", "нету",
               "недоступ", "исключ", "убери", "отсутств", "не интересу", "не нужно"]):
            exclude.add(ticker)
        elif any(re.search(rf'\b{re.escape(t_lower)}\s*{kw}\b', text_lower) for kw in ["нет", "нету", "отсутств",
               "недоступ", "исключ"]):
            exclude.add(ticker)

    rev_map = {v.lower(): v for v in RUSSIAN_NAMES.values()}
    for t_lower, ticker in rev_map.items():
        if any(kw + t_lower in text_lower for kw in ["без ", "кроме ", "нет "]):
            exclude.add(ticker)
        if any(t_lower + " " + kw in text_lower for kw in ["нет", "отсутств", "недоступ", "исключ"]):
            exclude.add(ticker)
        if t_lower in text_lower and any(kw in text_lower for kw in ["недоступ", "исключ",
                                                                     "не учитывай", "убери"]):
            exclude.add(ticker)

    for phrase, ticker in RUSSIAN_NAMES.items():
        if any(kw + phrase in text_lower for kw in ["без ", "кроме ", "нет ",
                                                    "недоступ", "исключ", "убери "]):
            exclude.add(ticker)
        if any(phrase + " " + kw in text_lower for kw in ["нет", "нету", "отсутств",
                                                          "недоступ", "исключ", "убери"]):
            exclude.add(ticker)

    return exclude


def _extract_allocation_amount(text: str) -> float | None:
    text_lower = text.lower().strip()
    alloc_keywords = ["вложить", "инвестировать", "распредели", "распределение", "allocate", "разложить", "разместить"]
    if not any(k in text_lower for k in alloc_keywords):
        return None
    numbers = re.findall(r"(\d[\d\s]*\d|\d)", text_lower.replace(",", ".").replace(" ", ""))
    if numbers:
        return float(numbers[-1])
    return None


async def _reply_with_allocation(update: Update, capital: float, exclude: set[str] | None = None):
    await update.message.reply_text(f"\U0001f50d Анализирую рынок для {capital:,.0f} ₽...")

    try:
        from src.portfolio.allocator import allocator

        picks = allocator.recommend(capital=capital, exclude=exclude)
        if not picks:
            msg = "Не удалось подобрать варианты. Запустите `finn update` для загрузки данных."
            await update.message.reply_text(msg)
            return

        text = f"\U0001f4b0 *Рекомендации для {capital:,.0f} ₽*"
        if exclude:
            text += f" (без {', '.join(sorted(exclude))})"
        text += "\n\n"

        for i, p in enumerate(picks[:10], 1):
            name = p.get("name") or p["ticker"]
            reason = p.get("reason", "")
            last_price = p.get("last_price")
            price_str = f"цена {last_price:.0f} ₽" if last_price else ""
            text += f"{i}. *{p['ticker']}* ({name}) — {p['category']}\n"
            text += f"   {price_str}\n"
            if reason:
                text += f"   \u2192 {reason}\n"
            risk = p.get("risk", {})
            if risk:
                parts = []
                if risk.get("var_95"):
                    parts.append(f"VaR95={risk['var_95']:.1f}%")
                if risk.get("stop_loss_pct"):
                    parts.append(f"SL={risk['stop_loss_pct']:.1f}%")
                if risk.get("suggested_shares"):
                    parts.append(f"лимит {risk['suggested_shares']} шт")
                if parts:
                    text += f"   📊 {' • '.join(parts)}\n"
            text += "\n"

        for chunk in _chunk_text(text, 4096):
            await update.message.reply_markdown(chunk)

        allocation_text = _format_allocation_plan(picks, capital)
        for chunk in _chunk_text(allocation_text, 4096):
            await update.message.reply_markdown(chunk)
    except Exception as e:
        logger.warning("Recommendation error", exc_info=True)
        await update.message.reply_text(f"\u274c Ошибка: {e}. Убедитесь, что запущен `finn update`.")


def _format_allocation_plan(picks: list[dict], capital: float) -> str:
    candidates = []
    for p in picks:
        score = p.get("score", 0)
        price = p.get("last_price")
        if score > 0 and price and price > 0:
            candidates.append(p)
    if not candidates:
        return ""

    total_score = sum(c["score"] for c in candidates)
    if total_score <= 0:
        return ""

    used = []
    remaining = capital
    for p in candidates:
        share = p["score"] / total_score
        amt = round(capital * share, 2)
        price = p["last_price"]
        if amt >= price:
            shares = int(amt / price)
            used.append({**p, "amount": amt, "shares": shares, "pct": share})
            remaining -= amt
        if len(used) >= 5:
            break

    if remaining > 0 and used:
        used[0]["amount"] = round(used[0]["amount"] + remaining, 2)
        used[0]["shares"] = int(used[0]["amount"] / (used[0]["last_price"] or 1))

    if not used:
        return ""

    text = "📊 *Как бы я распределил эти деньги:*\n\n"
    allocated = 0.0
    for item in used:
        allocated += item["amount"]
        text += f"• *{item['ticker']}* ({item.get('name', '')}): {item['amount']:,.0f} ₽ ({item['pct'] * 100:.0f}%)"
        if item["shares"] > 0:
            text += f" → ~{item['shares']} шт. по {item['last_price']:.0f} ₽"
        risk = item.get("risk", {})
        if risk:
            sl = risk.get("stop_loss")
            sl_pct = risk.get("stop_loss_pct")
            var = risk.get("var_95")
            if sl and sl_pct:
                text += f"\n   ⛔️ Стоп-лосс: {sl:.0f} ₽ ({sl_pct:.1f}%)"
            if var:
                text += f"\n   ⚠️ VaR(95%): {var:.1f}%"
        text += "\n"

    leftover = round(capital - allocated, 2)
    text += f"\n💰 *Итого:* {allocated:,.0f} из {capital:,.0f} ₽"
    if leftover > 0:
        text += f"\n💤 *Остаток:* {leftover:,.0f} ₽"
    return text


async def _ask_llm_general(update: Update, text: str):
    await update.message.reply_text("🤔 Думаю...")
    try:
        prompt = (
            f"Пользователь задал вопрос: {text}\n\n"
            "Ответь коротко и полезно — что купить, зачем, какие риски. "
            "Если вопрос про дивиденды — назови конкретные российские акции "
            "с примерными ценами и дивидендной доходностью. "
            "Если про небольшие суммы — подскажи, какие акции/БПИФ доступны "
            "для покупки от 500–1000 ₽. "
            "Не давай инвестиционных рекомендаций без оговорки о рисках."
        )
        messages = [
            {
                "role": "system",
                "content": "Ты — финансовый ассистент. "
                "Отвечай кратко, по делу, на русском. Называй конкретные тикеры и цены. "
                "Всегда добавляй предупреждение о рисках.",
            },
            {"role": "user", "content": prompt},
        ]

        if settings.groq_api_key:
            from groq import AsyncGroq

            client = AsyncGroq(api_key=settings.groq_api_key)
            response = await client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                temperature=0.3,
                max_tokens=512,
            )
            answer = response.choices[0].message.content
        else:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{settings.ollama_url}/api/chat",
                    json={
                        "model": settings.ollama_model,
                        "messages": messages,
                        "temperature": 0.3,
                        "max_tokens": 512,
                        "stream": False,
                    },
                )
                data = resp.json()
                answer = data.get("message", {}).get("content", "")

        if not answer:
            answer = "Не могу сформулировать ответ. Попробуйте уточнить вопрос или указать тикер через /analyze"

        for chunk in _chunk_text(answer, 4096):
            await update.message.reply_markdown(chunk)
    except Exception:
        logger.warning("LLM error", exc_info=True)
        await update.message.reply_text(
            "Не смог ответить на вопрос. Попробуйте:\n"
            "• /analyze SBER — анализ конкретной акции\n"
            "• /allocate 50000 — куда вложить деньги"
        )


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
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


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
    from src.notifications.service import NotificationService, format_signal_text

    ns = NotificationService()
    text = format_signal_text(n)
    for uid, cid in ns.get_subscribers("signal"):
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            ns.save_notification(uid, "signal", text, title=n.ticker)
        except Exception as e:
            logger.warning(f"Failed to send signal to {uid}: {e}")


async def broadcast_dividends():
    from src.notifications.service import NotificationService

    ns = NotificationService()
    dividends = ns.get_upcoming_dividends(days_ahead=14)
    if not dividends:
        return
    for uid, cid in ns.get_subscribers("dividend"):
        for d in dividends:
            text = (
                f"💵 *{d.ticker}* — дивиденды {d.amount:.0f} ₽/акц"
                + (f" ({d.yield_pct:.1f}%)" if d.yield_pct else "")
                + (f"\n📅 Дивидендная отсечка: {d.ex_date}" if d.ex_date else "")
            )
            try:
                await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
                ns.save_notification(uid, "dividend", text, title=d.ticker)
            except Exception as e:
                logger.warning(f"Failed to send dividend to {uid}: {e}")


async def broadcast_daily_summary():
    from src.notifications.service import NotificationService, format_daily_summary_text

    ns = NotificationService()
    summary = ns.get_daily_summary()
    text = format_daily_summary_text(summary)
    for uid, cid in ns.get_subscribers("daily"):
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            ns.save_notification(uid, "daily", text, title="Ежедневная сводка")
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
    app.add_handler(CommandHandler("stress", stress))
    app.add_handler(CommandHandler("backtest", backtest))

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
