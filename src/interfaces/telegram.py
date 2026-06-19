import asyncio
import io
import logging
import time
from typing import Optional

from collections import OrderedDict

from groq import AsyncGroq
import httpx

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.analysis.backtest import backtest_allocation
from src.analysis.sector import sector_analyzer
from src.analysis.correlation_analysis import correlation_table
from src.analysis.personal_backtest import run_personal_backtest
from src.analysis.stress import StressTester, format_portfolio_for_stress, format_sector_concentration, format_var_section
from src.analysis.whatif import whatif_macro, whatif_scenario
from src.cli import run_analysis
from src.collectors.cbr import CBRCollector
from src.config import personal, settings
from src.constants import CACHE_TTL, COOLDOWN_SECONDS, MAX_CACHE_SIZE
from src.db.connection import get_session
from src.db.models import GeoRiskScore, Instrument, Price, Signal as SignalModel, UserSetting
from src.db.models import Portfolio as PortModel
from src.interfaces.telegram_helpers import (
    ACTION_EMOJI,
    _chunk_text,
    _extract_allocation_amount,
    _find_excluded_tickers,
    _find_tickers,
    _format_allocation_plan,
    _simplify_reasons,
    build_analyze_keyboard,
    build_main_keyboard,
    build_top_keyboard,
    get_portfolio_positions,
)
from src.notifications.service import NotificationService, format_daily_summary_text, format_signal_text
from src.portfolio.allocator import allocator
from src.reports import generate_portfolio_csv

logger = logging.getLogger(__name__)

analysis_cache: OrderedDict[str, tuple[float, dict, str]] = OrderedDict()

_user_cooldowns: dict[int, float] = {}

TICKER, QUANTITY, PRICE = range(3)


ALLOWED_IDS: set[int] = set()
_raw = settings.telegram_allowed_ids
if _raw:
    for part in _raw.split(","):
        part = part.strip()
        if part.isdigit():
            ALLOWED_IDS.add(int(part))


async def _check_access(update: Update) -> bool:
    if not ALLOWED_IDS:
        return True
    uid = update.effective_user.id if update.effective_user else 0
    if uid in ALLOWED_IDS:
        return True
    if update.effective_message:
        await update.effective_message.reply_text("⛔ Доступ запрещён. Ваш Telegram ID не в списке разрешённых.")
    return False


async def _check_cooldown(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    now = time.time()
    last = _user_cooldowns.get(uid, 0)
    if now - last < COOLDOWN_SECONDS:
        if update.effective_message:
            await update.effective_message.reply_text("⏳ Подождите немного перед следующим запросом.")
        return False
    _user_cooldowns[uid] = now
    return True


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split(":", 1)
    msg = query.message

    if parts[0] == "analyze" and len(parts) > 1:
        ticker = parts[1]
        if msg:
            await msg.reply_text(f"\U0001f50d Анализирую {ticker}...")
        await _reply_with_analysis(update, ticker)

    elif parts[0] == "add" and len(parts) > 1:
        ticker = parts[1]
        context.args = [ticker, "1"]
        await add_position(update, context)

    elif parts[0] == "history" and len(parts) > 1:
        ticker = parts[1]
        context.args = [ticker]
        await history(update, context)

    elif parts[0] == "backtest" and len(parts) > 1:
        ticker = parts[1]
        context.args = [ticker]
        await backtest(update, context)

    elif parts[0] == "action" and len(parts) > 1:
        action = parts[1]
        if action == "portfolio":
            await portfolio(update, context)
        elif action == "daily":
            await daily(update, context)
        elif action == "sectors":
            await sectors(update, context)
        elif action == "top":
            await top(update, context)
        elif action == "stress":
            await stress(update, context)
        elif action == "export":
            await export_portfolio(update, context)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
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
        "/backtest — история стратегии\n"
        "/profile — риск-профиль (conservative/balanced/aggressive)\n"
        "/add SBER 10 — добавить в портфель\n"
        "/remove SBER — удалить из портфеля\n"
        "/history SBER — история сигналов\n"
        "/sectors — сектора рынка\n"
        "/top — лучшие возможности\n"
        "/export — CSV-отчёт портфеля\n\n"
        "Используйте кнопки для быстрого доступа \u2935\ufe0f",
        reply_markup=build_main_keyboard(),
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or update.effective_user is None or update.effective_chat is None:
        return
    if not await _check_cooldown(update):
        return
    uid = update.effective_user.id
    cid = update.effective_chat.id
    args = context.args or []
    ntype = args[0] if args else "signal"
    if ntype not in ("signal", "daily", "geo", "dividend"):
        ntype = "signal"

    ns = NotificationService()
    ns.subscribe(uid, cid, ntype)
    type_names = {"signal": "сигналы", "daily": "ежедневные сводки", "geo": "гео-риски", "dividend": "дивиденды"}
    await update.effective_message.reply_text(f"✅ Вы подписаны на {type_names.get(ntype, ntype)}")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or update.effective_user is None:
        return
    if not await _check_cooldown(update):
        return
    uid = update.effective_user.id
    args = context.args or []
    ntype = args[0] if args else None
    ns = NotificationService()
    ns.unsubscribe(uid, ntype)
    if ntype:
        await update.effective_message.reply_text("❌ Подписка на этот тип уведомлений отменена")
    else:
        await update.effective_message.reply_text("❌ Все подписки отменены")


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    ns = NotificationService()
    summary = ns.get_daily_summary()
    text = format_daily_summary_text(summary)
    await update.effective_message.reply_markdown(text)


async def allocate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    if not context.args:
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


async def stress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return

    amount = None
    if context.args:
        try:
            amount = float(context.args[0].replace(" ", "").replace(",", "."))
        except ValueError:
            pass

    if amount:

        await update.effective_message.reply_text(f"🔬 Рассчитываю сценарии для {amount:,.0f} ₽...")
        picks = allocator.recommend(capital=amount)
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
                for r in rows if r["value"] > 0
            ]
        finally:
            db.close()

    if not positions:
        await update.effective_message.reply_text("Нет позиций для тестирования. Добавьте портфель или укажите сумму.")
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
        await update.effective_message.reply_markdown(chunk)


async def backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return

    amount: float = 100_000
    if context.args:
        try:
            amount = float(context.args[0].replace(" ", "").replace(",", "."))
            if amount < 500:
                await update.effective_message.reply_text("Минимальная сумма — 500 ₽")
                return
        except ValueError:
            pass

    await update.effective_message.reply_text(f"🕰 Прогоняю стратегию для {amount:,.0f} ₽ за последний год...")
    result = backtest_allocation(capital=amount)
    await update.effective_message.reply_markdown(result.summary())


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Укажите тикер: /history SBER")
        return
    ticker = args[0].upper()

    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            await update.effective_message.reply_text(f"{ticker} не найден")
            return
        signals = (
            db.query(SignalModel).filter_by(instrument_id=inst.id).order_by(SignalModel.date.desc()).limit(60).all()
        )
        if not signals:
            await update.effective_message.reply_text(f"Нет истории сигналов для {ticker}")
            return

        lines = [f"📈 *История сигналов — {ticker}*\n"]
        for s in reversed(signals):
            emoji = "🟢" if s.action in ("BUY", "CAUTIOUS_BUY") else "🔴" if s.action == "SELL" else "⚪"
            conf = s.confidence or 0
            lines.append(f"{emoji} {s.date}  **{s.action}** _{conf:.0%}_")
        await update.effective_message.reply_markdown("\n".join(lines))
    finally:
        db.close()


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    args = context.args or []
    ticker = args[0].upper() if args else None
    if not ticker:
        await update.effective_message.reply_text("Укажите тикер: /analyze SBER")
        return
    await _reply_with_analysis(update, ticker)


async def sectors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return

    await update.effective_message.reply_text("🏭 Анализирую сектора...")
    db = get_session()
    try:
        perf = sector_analyzer.compute_sector_performance(db)
        vol = sector_analyzer.compute_sector_volatility(db)
        lines = ["🏭 *Доходность секторов (30д):*\n"]
        sorted_sectors = sorted(perf.items(), key=lambda x: x[1], reverse=True)
        for sector, perf_val in sorted_sectors:
            emoji = "\U0001f7e2" if perf_val > 0 else "\U0001f534"
            v = vol.get(sector, "")
            vol_str = f" (волат. {v:.0%})" if isinstance(v, float) else ""
            lines.append(f"{emoji} {sector}: {perf_val:+.1%}{vol_str}")

        await update.effective_message.reply_markdown("\n".join(lines))
    finally:
        db.close()


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    await update.effective_message.reply_text("🏆 Ищу лучшие возможности...")
    try:

        picks = allocator.recommend(capital=100_000)
        if not picks:
            await update.effective_message.reply_text("Нет данных. Запустите `finn update`.")
            return

        text = "🏆 *Топ-10 возможностей:*\n\n"
        for i, p in enumerate(picks[:10], 1):
            score = p.get("score", 0)
            name = p.get("name") or p["ticker"]
            text += f"{i}. *{p['ticker']}* — score {score:.2f}\n"
            text += f"   {p['category']} | {name}\n"
            reason = p.get("reason", "")
            if reason:
                text += f"   \u2192 {reason}\n"
            text += "\n"

        await update.effective_message.reply_markdown(text, reply_markup=build_top_keyboard())
    except Exception:
        logger.warning("Top command error", exc_info=True)
        await update.effective_message.reply_text("\u274c Не удалось загрузить топ. Убедитесь, что запущен `finn update`.")


async def export_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return

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


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.effective_message.reply_text("Задайте вопрос, например: /ask Что думаешь про SBER?")
        return
    await _handle_text(update, text)


async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    await _handle_text(update, update.effective_message.text)


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
            await update.effective_message.reply_text(f"Нашёл несколько, анализирую {ticker}")
        await _reply_with_analysis(update, ticker)
        return
    await _ask_llm_general(update, text)


async def _reply_with_analysis(update: Update, ticker: str):
    now = time.time()
    cached = analysis_cache.get(ticker)
    if cached and (now - cached[0]) < CACHE_TTL:
        fused, advice = cached[1], cached[2]
        logger.info("Using cached analysis for %s", ticker)
        msg = None
    else:
        msg = await update.effective_message.reply_text(f"\U0001f50d Анализирую {ticker}...")
        try:
            fused, advice = await run_analysis(ticker, with_llm=True)
            analysis_cache[ticker] = (now, fused, advice)
            if len(analysis_cache) > MAX_CACHE_SIZE:
                analysis_cache.popitem(last=False)
        except Exception:
            logger.exception("Analysis error for %s", ticker)
            await msg.edit_text(
                "\u274c Не удалось проанализировать. Убедитесь, что запущен `finn update`."
            )
            return

    if not fused:
        await update.effective_message.reply_text(f"\u274c {advice}")
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
    text += f"\n\n\U0001f4a1 Рекомендуемая доля: до {fused['max_portfolio_pct']}%"

    chunks = _chunk_text(text, 4096)
    if msg:
        await msg.edit_text(chunks[0], parse_mode="Markdown", reply_markup=build_analyze_keyboard(ticker))
    else:
        await update.effective_message.reply_markdown(chunks[0], reply_markup=build_analyze_keyboard(ticker))
    for chunk in chunks[1:]:
        await update.effective_message.reply_markdown(chunk, reply_markup=build_analyze_keyboard(ticker))


async def _reply_with_allocation(update: Update, capital: float, exclude: set[str] | None = None):
    msg = await update.effective_message.reply_text(f"\U0001f50d Анализирую рынок для {capital:,.0f} ₽...")

    try:

        picks = allocator.recommend(capital=capital, exclude=exclude)
        if not picks:
            await msg.edit_text("Не удалось подобрать варианты. Запустите `finn update` для загрузки данных.")
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
                    parts.append(f"риск падения {risk['var_95']:.1f}%/день")
                if risk.get("stop_loss_pct"):
                    parts.append(f"стоп-лосс {risk['stop_loss_pct']:.1f}%")
                if risk.get("suggested_shares"):
                    parts.append(f"макс. {risk['suggested_shares']} шт")
                if parts:
                    text += f"   {' • '.join(parts)}\n"
            text += "\n"

        chunks = _chunk_text(text, 4096)
        allocation_text = _format_allocation_plan(picks, capital)
        alloc_chunks = _chunk_text(allocation_text, 4096) if allocation_text else []

        await msg.edit_text(chunks[0], parse_mode="Markdown")
        for chunk in chunks[1:]:
            await update.effective_message.reply_markdown(chunk)
        for chunk in alloc_chunks:
            await update.effective_message.reply_markdown(chunk)
    except Exception:
        logger.warning("Recommendation error", exc_info=True)
        await msg.edit_text("\u274c Не удалось рассчитать рекомендации. Убедитесь, что запущен `finn update`.")


async def _ask_llm_general(update: Update, text: str):
    msg = await update.effective_message.reply_text("🤔 Думаю...")
    try:
        system_content = personal.get("llm_system_prompt") or (
            "Ты — финансовый ассистент. "
            "Отвечай кратко, по делу, на русском. Называй конкретные тикеры и цены. "
            "Всегда добавляй предупреждение о рисках."
        )
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
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

        if settings.groq_api_key:

            client = AsyncGroq(api_key=settings.groq_api_key)
            response = await client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                temperature=0.3,
                max_tokens=512,
            )
            answer = response.choices[0].message.content
        else:

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

        chunks = _chunk_text(answer, 4096)
        await msg.edit_text(chunks[0], parse_mode="Markdown")
        for chunk in chunks[1:]:
            await update.effective_message.reply_markdown(chunk)
    except Exception:
        logger.warning("LLM error", exc_info=True)
        await msg.edit_text(
            "Не смог ответить на вопрос. Попробуйте:\n"
            "• /analyze SBER — анализ конкретной акции\n"
            "• /allocate 50000 — куда вложить деньги"
        )


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return

    msg = await update.effective_message.reply_text("⏳ Синхронизация с T-Bank...")
    try:
        from src.trading.brokers.sync import sync_portfolio_from_broker
        sync_result = await sync_portfolio_from_broker()
        if sync_result.get("status") == "no_token":
            await msg.edit_text("❌ TINKOFF_TOKEN не настроен")
            return
        if sync_result.get("status") == "no_accounts":
            await msg.edit_text("❌ Нет счетов в T-Bank")
            return
    except Exception as e:
        logger.warning("Sync failed: %s", e)

    db = get_session()
    try:
        rows = get_portfolio_positions(db)
        if not rows:
            try:
                from src.trading.brokers.tbank import TBankClient
                async with TBankClient(use_sandbox=settings.tinkoff_sandbox) as tbank:
                    accounts = await tbank.get_accounts()
                    if accounts:
                        balance = await tbank.get_account_balance(accounts[0]["id"])
                        await msg.edit_text(
                            f"📭 *Портфель пуст*\n\n"
                            f"💵 Доступно: {balance:,.0f} ₽\n\n"
                            f"Сигналы пока не дают BUY/SELL.\n"
                            f"Текущие сигналы: `/portfolio` (обновляется раз в час)",
                            parse_mode="Markdown"
                        )
                        return
                await msg.edit_text("📭 Портфель пуст. Нет счетов в T-Bank.")
                return
            except Exception as e:
                logger.warning("Failed to get balance: %s", e)
                await msg.edit_text("📭 Портфель пуст. Нет позиций.")
                return

        lines = ["📊 *Портфель (T-Bank)*\n"]
        total_value = 0.0
        total_cost = 0.0
        for r in rows:
            qty = r["quantity"]
            avg = r["avg_price"]
            cur = r["current_price"]
            val = r["value"]
            cost = avg * qty
            pnl = val - cost
            pnl_pct = ((cur / avg) - 1) * 100 if avg > 0 else 0.0
            emoji = "🟢" if pnl >= 0 else "🔴"

            lines.append(
                f"{emoji} *{r['ticker']}*: {qty:.0f} шт × {cur:.2f} ₽\n"
                f"   Средняя: {avg:.2f} | Стоимость: {val:,.0f} ₽\n"
                f"   P&L: {pnl:+,.0f} ₽ ({pnl_pct:+.1f}%)"
            )
            total_value += val
            total_cost += cost

        total_pnl = total_value - total_cost
        total_pnl_pct = ((total_value / total_cost) - 1) * 100 if total_cost > 0 else 0.0
        total_emoji = "🟢" if total_pnl >= 0 else "🔴"
        lines.append(
            f"\n{total_emoji} *Итого:* {total_value:,.0f} ₽"
            f" | P&L: {total_pnl:+,.0f} ₽ ({total_pnl_pct:+.1f}%)"
        )
        await msg.edit_text("\n".join(lines), parse_mode="Markdown")
    finally:
        db.close()


async def _save_position(update: Update, ticker: str, qty: float, avg_price: float | None = None):
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            await update.effective_message.reply_text(
                f"Инструмент {ticker} не найден в базе. Запустите `finn update {ticker}`."
            )
            return
        if avg_price is None:
            price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
            avg_price = price.close if price else 0

        existing = db.query(PortModel).filter_by(instrument_id=inst.id).first()
        if existing:
            existing.quantity += qty
            if existing.avg_price and avg_price:
                total_qty = existing.quantity
                existing.avg_price = (existing.avg_price * (total_qty - qty) + avg_price * qty) / total_qty
            db.commit()
            await update.effective_message.reply_text(f"✅ {ticker}: добавлено {qty} шт. (всего {existing.quantity:.1f} шт.)")
        else:
            pos = PortModel(instrument_id=inst.id, quantity=qty, avg_price=avg_price)
            db.add(pos)
            db.commit()
            await update.effective_message.reply_text(f"✅ {ticker}: {qty} шт. добавлено в портфель")
    except Exception:
        db.rollback()
        logger.warning("Save position error", exc_info=True)
        await update.effective_message.reply_text("❌ Не удалось добавить позицию. Попробуйте позже.")
    finally:
        db.close()


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return ConversationHandler.END
    if not update.effective_message:
        return ConversationHandler.END
    if not await _check_cooldown(update):
        return ConversationHandler.END
    args = context.args or []
    if len(args) >= 2:
        ticker = args[0].upper()
        try:
            qty = float(args[1].replace(",", "."))
        except ValueError:
            await update.effective_message.reply_text("Количество должно быть числом: /add SBER 10")
            return ConversationHandler.END
        await _save_position(update, ticker, qty)
        return ConversationHandler.END

    await update.effective_message.reply_text("Введите *тикер* инструмента (например, SBER):", parse_mode="Markdown")
    return TICKER


async def add_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return ConversationHandler.END
    context.user_data["add_ticker"] = update.effective_message.text.strip().upper()
    await update.effective_message.reply_text("Введите *количество* (например, 10):", parse_mode="Markdown")
    return QUANTITY


async def add_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return ConversationHandler.END
    try:
        qty = float(update.effective_message.text.strip().replace(",", "."))
        context.user_data["add_qty"] = qty
    except ValueError:
        await update.effective_message.reply_text("Количество должно быть числом. Попробуйте ещё раз:", parse_mode="Markdown")
        return QUANTITY
    await update.effective_message.reply_text(
        "Введите *среднюю цену* (или отправьте `-` для автоматической):",
        parse_mode="Markdown",
    )
    return PRICE


async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return ConversationHandler.END
    text = update.effective_message.text.strip()
    if text == "-":
        avg_price = None
    else:
        try:
            avg_price = float(text.replace(",", "."))
        except ValueError:
            await update.effective_message.reply_text("Цена должна быть числом или `-`. Попробуйте ещё раз:", parse_mode="Markdown")
            return PRICE

    ticker = context.user_data.get("add_ticker", "")
    qty = context.user_data.get("add_qty", 0)
    context.user_data.clear()
    await _save_position(update, ticker, qty, avg_price)
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text("❌ Добавление отменено")
    return ConversationHandler.END


async def remove_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    args = context.args or []
    if len(args) < 1:
        await update.effective_message.reply_text("Укажите тикер: /remove SBER")
        return
    ticker = args[0].upper()
    qty = None
    if len(args) >= 2:
        try:
            qty = float(args[1].replace(",", "."))
        except ValueError:
            pass

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
        db.rollback()
        logger.warning("Remove position error", exc_info=True)
        await update.effective_message.reply_text("❌ Не удалось удалить позицию. Попробуйте позже.")
    finally:
        db.close()


async def rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return

    cbr = CBRCollector()
    try:
        rates = await cbr.get_rates()
        majors = ["USD", "EUR", "CNY", "GBP", "KZT", "TRY"]
        lines = ["\U0001f3e6 Курсы ЦБ РФ:\n"]
        for r in rates:
            if r["code"] in majors:
                lines.append(f"  {r['code']}: {r['value']:.2f} \u20bd")
        await update.effective_message.reply_text("\n".join(lines))
    except Exception:
        logger.warning("Rates error", exc_info=True)
        await update.effective_message.reply_text("\u274c Не удалось получить курсы. Попробуйте позже.")


async def geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return

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
            await update.effective_message.reply_text(
                f"\U0001f30d Геополитический риск: {score.score}/10 ({level})\nДата: {score.date}"
            )
        else:
            await update.effective_message.reply_text("Нет данных. Запустите daily update.")
    finally:
        db.close()


async def _ns_get_subscribers(ns: NotificationService, notify_type: str = "signal") -> list[tuple[int, int]]:
    return await asyncio.to_thread(ns.get_subscribers, notify_type)


async def _ns_get_upcoming_dividends(ns: NotificationService, days_ahead: int = 14) -> list:
    return await asyncio.to_thread(ns.get_upcoming_dividends, days_ahead)


async def _ns_get_daily_summary(ns: NotificationService):
    return await asyncio.to_thread(ns.get_daily_summary)


async def _ns_save_notification(ns: NotificationService, uid: int, notify_type: str, text: str, title: str = ""):
    await asyncio.to_thread(ns.save_notification, uid, notify_type, text, title)


async def broadcast_signal(n):
    if app is None:
        logger.warning("Bot not running, skipping signal broadcast")
        return

    ns = NotificationService()
    text = format_signal_text(n)
    subscribers = await _ns_get_subscribers(ns, "signal")
    for uid, cid in subscribers:
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            await _ns_save_notification(ns, uid, "signal", text, title=n.ticker)
        except Exception as e:
            logger.warning(f"Failed to send signal to {uid}: {e}")


async def broadcast_dividends():
    if app is None:
        logger.warning("Bot not running, skipping dividend broadcast")
        return

    ns = NotificationService()
    dividends = await _ns_get_upcoming_dividends(ns, days_ahead=14)
    if not dividends:
        return
    subscribers = await _ns_get_subscribers(ns, "dividend")
    for uid, cid in subscribers:
        for d in dividends:
            text = (
                f"💵 *{d.ticker}* — дивиденды {d.amount:.0f} ₽/акц"
                + (f" ({d.yield_pct:.1f}%)" if d.yield_pct else "")
                + (f"\n📅 Дивидендная отсечка: {d.ex_date}" if d.ex_date else "")
            )
            try:
                await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
                await _ns_save_notification(ns, uid, "dividend", text, title=d.ticker)
            except Exception as e:
                logger.warning(f"Failed to send dividend to {uid}: {e}")


async def broadcast_daily_summary():
    if app is None:
        logger.warning("Bot not running, skipping daily summary broadcast")
        return

    ns = NotificationService()
    summary = await _ns_get_daily_summary(ns)
    text = format_daily_summary_text(summary)
    subscribers = await _ns_get_subscribers(ns, "daily")
    for uid, cid in subscribers:
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            await _ns_save_notification(ns, uid, "daily", text, title="Ежедневная сводка")
        except Exception as e:
            logger.warning(f"Failed to send daily to {uid}: {e}")


async def broadcast_trade(
    ticker: str,
    direction: str,
    quantity: int,
    price: float,
    status: str,
    reason: str = "",
    order_id: str = "",
    portfolio_value: Optional[float] = None,
):
    if app is None:
        logger.warning("Bot not running, skipping trade broadcast")
        return

    emoji = "🟢" if direction == "BUY" else "🔴"
    text = (
        f"{emoji} *{ticker}* — {direction} {quantity} шт. по {price:.2f} ₽\n"
        f"Статус: {status}"
    )
    if reason:
        text += f"\n📌 Причина: {reason}"
    if order_id:
        text += f"\n🆔 Заявка: `{order_id[:12]}...`"
    if portfolio_value is not None:
        text += f"\n💵 Портфель: {portfolio_value:,.0f} ₽"

    ns = NotificationService()
    for uid, cid in ns.get_subscribers("trade"):
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            ns.save_notification(uid, "trade", text, title=ticker)
        except Exception as e:
            logger.warning(f"Failed to send trade to {uid}: {e}")


app: Optional[Application] = None


async def correlation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    tickers = list(context.args) if context.args else None
    text = correlation_table(tickers)
    for chunk in _chunk_text(text, 4096):
        await update.effective_message.reply_markdown(chunk)


async def whatif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(
            "Укажите сценарий:\n"
            "• `/whatif SBER -0.2` — падение SBER на 20%\n"
            "• `/whatif oil40` — нефть по $40\n"
            "• `/whatif rate25` — ставка 25%\n"
            "• `/whatif rubdown20` — рубль -20%\n"
            "• `/whatif sanctions2022` — санкции 2022\n"
            "• `/whatif covid2020` — COVID-19"
        )
        return

    portfolio_value = 1_000_000

    macro_scenarios = {"oil40", "rate25", "rubdown20", "sanctions2022", "covid2020"}
    if args[0] in macro_scenarios:
        text = whatif_macro(args[0], portfolio_value)
    else:
        ticker = args[0].upper()
        try:
            shock = float(args[1]) if len(args) > 1 else -0.1
        except ValueError:
            await update.effective_message.reply_text("Шок должен быть числом, например -0.2")
            return
        text = whatif_scenario(ticker, shock, portfolio_value)

    for chunk in _chunk_text(text, 4096):
        await update.effective_message.reply_markdown(chunk)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return

    from src.config import personal

    db = get_session()
    try:
        row = db.query(UserSetting).filter_by(key="risk_profile").first()
        current = row.value if row else "balanced"

        if context.args:
            new_profile = context.args[0].lower()
            if new_profile not in ("conservative", "balanced", "aggressive"):
                await update.effective_message.reply_text("Доступные профили: conservative, balanced, aggressive")
                return

            allocator.set_profile(new_profile)
            if row:
                row.value = new_profile
            else:
                db.add(UserSetting(key="risk_profile", value=new_profile))
            db.commit()
            names = {"conservative": "Консервативный", "balanced": "Сбалансированный", "aggressive": "Агрессивный"}
            await update.effective_message.reply_text(f"✅ Профиль изменён на *{names[new_profile]}*")
        else:
            names = {"conservative": "Консервативный", "balanced": "Сбалансированный", "aggressive": "Агрессивный"}
            desc = {
                "conservative": "50% ETF, 25% облигации, 20% дивидендные, 5% рост",
                "balanced": "40% ETF, 30% дивидендные, 20% облигации, 10% рост",
                "aggressive": "40% рост, 25% ETF, 25% дивидендные, 10% облигации",
            }
            text = f"📊 *Личные настройки*\n\n"
            text += f"👤 Профиль риска: *{names.get(current, current)}*\n"

            p_capital = personal.get("capital", 100_000)
            p_tickers = personal.get("favorite_tickers", [])
            p_horizon = personal.get("investment_horizon", "medium")
            horizon_label = {"short": "Краткосрочный", "medium": "Среднесрочный", "long": "Долгосрочный"}
            text += f"💰 Капитал: {p_capital:,.0f} ₽\n"
            text += f"📅 Горизонт: {horizon_label.get(p_horizon, p_horizon)}\n"
            if p_tickers:
                text += f"⭐ Избранные: {', '.join(p_tickers[:10])}\n"

            text += "\n*Сменить профиль:*\n"
            for k, name in names.items():
                text += f"• `/profile {k}` — {name} ({desc[k]})\n"
            await update.effective_message.reply_markdown(text)
    finally:
        db.close()


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
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
        logger.warning("Report error", exc_info=True)
        await msg.edit_text("❌ Ошибка формирования отчёта.")


async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if not await _check_cooldown(update):
        return
    from src.trading.execution.audit import get_trade_history
    from src.trading.risk.guards import get_day_pnl

    pnl, pnl_pct = get_day_pnl()
    trades = get_trade_history(limit=10)
    text = f"📊 *P&L*\n\n"
    text += f"Сегодня: {pnl:+,.0f} ₽ ({pnl_pct:+.2%})\n\n"
    if trades:
        text += "*Последние сделки:*\n"
        for t in trades[:5]:
            emoji = "🟢" if t["pnl"] and t["pnl"] >= 0 else "🔴"
            text += f"{emoji} {t['ticker']} {t['direction']} {t['quantity']}шт @ {t['price']:.2f}"
            if t["pnl"]:
                text += f" ({t['pnl']:+.0f} ₽)"
            text += "\n"
    if not trades:
        text += "Сделок пока нет."
    for chunk in _chunk_text(text, 4096):
        await update.effective_message.reply_markdown(chunk)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text("Произошла внутренняя ошибка. Попробуйте позже.")


async def run_bot():
    global app
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set in .env")
        return

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_error_handler(error_handler)

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
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("add", add_start)],
            states={
                TICKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ticker)],
                QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_quantity)],
                PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            },
            fallbacks=[CommandHandler("cancel", add_cancel)],
        )
    )
    app.add_handler(CommandHandler("remove", remove_position))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("sectors", sectors))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("export", export_portfolio))
    app.add_handler(CommandHandler("correlation", correlation))
    app.add_handler(CommandHandler("whatif", whatif))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("pnl", pnl))

    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    logger.info("Bot started polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Bot shutting down...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())
