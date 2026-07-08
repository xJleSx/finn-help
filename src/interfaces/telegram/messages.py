import time
from typing import Any

import structlog
from telegram import Update

from src.cli import run_analysis
from src.constants import CACHE_TTL, MAX_CACHE_SIZE
from src.db.connection import get_session
from src.db.models import Instrument, Price
from src.db.models import Portfolio as PortModel
from src.interfaces.telegram_guard import analysis_cache
from src.interfaces.telegram_helpers import (
    ACTION_EMOJI,
    _chunk_text,
    _extract_allocation_amount,
    _find_excluded_tickers,
    _find_tickers,
    _format_allocation_plan,
    build_analyze_keyboard,
    html_escape,
)
from src.portfolio.allocator import allocator

logger = structlog.get_logger(__name__)

DETAILED_KEYWORDS = {
    "анализ",
    "подробн",
    "минимальн",
    "максимальн",
    "прогноз",
    "перспектив",
    "сколько",
    "почему",
    "будет",
    "изменил",
    "вырос",
    "упал",
    "снизил",
    "повысил",
    "динамик",
    "покажи",
    "расскажи",
    "объясни",
    "оцени",
    "сравни",
    "каков",
    "какова",
    "каково",
    "какие",
    "какой",
    "какое",
    "какая",
    "стоит",
    "что",
    "когда",
    "зачем",
    "цена",
    "стоимость",
    "дайте",
    "нужн",
    "хоч",
    "подскаж",
    "посоветуй",
    "насколько",
    "во сколько",
    "какую",
    "каком",
    "какому",
    "какими",
}


def _is_detailed_question(text: str, ticker: str) -> bool:
    words = text.lower().split()
    if len(words) <= 1:
        return False
    from src.interfaces.telegram_helpers import RUSSIAN_NAMES

    ticker_variants = {ticker.lower()}
    for russian_name, eng_ticker in RUSSIAN_NAMES.items():
        if eng_ticker == ticker.upper():
            ticker_variants.add(russian_name)
    other_words = [w for w in words if w not in ticker_variants]
    if not other_words:
        return False
    return any(kw in w for w in other_words for kw in DETAILED_KEYWORDS)


def _build_stock_context(ticker: str) -> str:
    try:
        from src.analysis.service import analysis_service
        from src.db.connection import get_session

        db = get_session()
        try:
            return analysis_service.load_ticker_context(db, ticker)
        finally:
            db.close()
    except Exception:
        logger.exception("Unhandled exception")
        return ""


def _describe_risk(sharpe: float, max_dd: float) -> str:
    parts = []
    if sharpe < 0.3:
        parts.append("доходность нестабильна")
    elif sharpe < 1.0:
        parts.append("доходность умеренная")
    else:
        parts.append("доходность хорошая")

    if max_dd > 0.3:
        parts.append("возможны просадки до 30%+")
    elif max_dd > 0.15:
        parts.append("просадки в пределах разумного")
    else:
        parts.append("просадки небольшие")
    return ", ".join(parts)


def _format_data_advice(fused: dict[str, Any]) -> str:
    parts = []
    components = fused.get("components", {})
    risk = fused.get("risk_metrics", {})
    vol = fused.get("volatility_regime", {})

    tech = components.get("technical", {})
    if tech:
        tech_score = tech.get("score", 0)
        tech_action = tech.get("action", "NEUTRAL")
        tech_labels = {
            "BUY": "сигнал к покупке",
            "SELL": "сигнал к продаже",
            "HOLD": "нейтрально, держать",
            "NEUTRAL": "нейтрально",
        }
        desc = tech_labels.get(tech_action, tech_action.lower())
        extra = ""
        if tech_score > 0.3:
            extra = " — технические индикаторы на стороне покупателей"
        elif tech_score < -0.3:
            extra = " — технические индикаторы на стороне продавцов"
        parts.append(f"📊 <b>Технический анализ</b>: {desc}{extra}")

    if risk:
        sharpe = risk.get("sharpe", 0)
        max_dd = risk.get("max_drawdown", 0)
        desc = _describe_risk(sharpe, max_dd)
        parts.append(f"📈 <b>Риски</b>: {desc}")

    vol_regime = vol.get("regime", "") if vol else ""
    if vol_regime == "HIGH":
        parts.append("🌊 <b>Волатильность</b>: высокая — цена может резко меняться")
    elif vol_regime == "LOW":
        parts.append("🌊 <b>Волатильность</b>: низкая — цена стабильна")
    elif vol_regime:
        parts.append("🌊 <b>Волатильность</b>: обычная")

    sent = components.get("sentiment", {})
    sent_score = sent.get("score", 0) if sent else 0
    if sent_score > 0.1:
        parts.append("📰 <b>Новости</b>: позитивные — рынок поддерживает актив")
    elif sent_score < -0.1:
        parts.append("📰 <b>Новости</b>: негативные — вокруг актива больше плохих новостей")
    elif sent_score != 0:
        parts.append("📰 <b>Новости</b>: нейтральные")

    ml = components.get("ml", {})
    ml_change = ml.get("change_pct") if ml else None
    if ml_change is not None:
        direction = "рост" if ml_change > 0 else "снижение"
        tp = ml.get("target_price")
        line = f"🤖 <b>Прогноз модели</b>: {direction} {abs(ml_change):.1f}%"
        if tp:
            line += f" (цель {tp:.0f} ₽)"
        parts.append(line)

    trends = fused.get("trends", {})
    if trends:
        daily = trends.get("daily", {})
        weekly = trends.get("weekly", {})
        trend_parts = []
        pd_ = daily.get("price_delta") if daily else None
        if pd_ is not None:
            arrow = "📈" if pd_ > 0 else "📉"
            trend_parts.append(f"{arrow} цена {'выросла' if pd_ > 0 else 'снизилась'} на {abs(pd_):.1f}% за день")
        pw = weekly.get("price_delta") if weekly else None
        if pw is not None:
            arrow = "📈" if pw > 0 else "📉"
            trend_parts.append(f"{arrow} за неделю {'+' + str(round(pw, 1)) if pw > 0 else str(round(pw, 1))}%")
        if weekly:
            ac = weekly.get("action_changed")
            if ac:
                trend_parts.append("🔄 рекомендация изменилась за неделю")
        if trend_parts:
            parts.append("")
            parts.extend(trend_parts)

    if parts:
        return "\n".join(parts)
    return ""


async def _reply_with_analysis(update: Update, ticker: str) -> None:
    if not update.effective_message:
        return
    now = time.time()
    cached = analysis_cache.get(ticker)
    fused: dict[str, Any] | None
    _advice: str
    if cached and (now - cached[0]) < CACHE_TTL:
        fused, _advice = cached[1], cached[2]
        logger.info("Using cached analysis for %s", ticker)
        msg = None
    else:
        msg = await update.effective_message.reply_text(f"\U0001f50d Анализирую {ticker}...")
        try:
            fused, _advice = await run_analysis(ticker, with_llm=False)
            analysis_cache[ticker] = (now, fused, _advice)
            if len(analysis_cache) > MAX_CACHE_SIZE:
                analysis_cache.popitem(last=False)
        except Exception:
            logger.exception("Unhandled exception")
            logger.exception("Analysis error for %s", ticker)
            await msg.edit_text("\u274c Не удалось проанализировать. Убедитесь, что запущен `finn update`.")
            return

    if not fused:
        await update.effective_message.reply_text(f"\u274c {_advice}")
        return

    action = fused.get("action", "HOLD")
    confidence = fused.get("confidence", 0)
    emoji = ACTION_EMOJI.get(action, "\u26aa")

    action_labels = {
        "BUY": "можно покупать",
        "CAUTIOUS_BUY": "можно присмотреться",
        "HOLD": "лучше держать",
        "SELL": "лучше продать",
        "NEUTRAL": "нейтрально",
    }
    label = action_labels.get(action, action.lower())

    text = f"{emoji} <b>{html_escape(ticker)}</b> — {label}\n"
    text += f"Уверенность: {confidence:.0%}\n"

    from src.db.connection import get_session
    from src.interfaces.response_formatter import (
        build_corporate_events_block,
        build_financial_highlights,
        build_profile_block,
        load_company_profile,
        load_financial_report,
        load_upcoming_events,
    )

    _db = get_session()
    try:
        inst = _db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if inst:
            profile = load_company_profile(_db, inst.id)
            pb = build_profile_block(profile) if profile else ""
            if pb:
                text += f"\n🏢 <b>Профиль:</b>\n{html_escape(pb)}\n"

            report = load_financial_report(_db, inst.id)
            fh = build_financial_highlights(report)
            if fh:
                text += "\n📊 <b>Финансовые highlights:</b>\n"
                for hl in fh:
                    text += f"• {html_escape(hl)}\n"

            events = load_upcoming_events(_db, inst.id, days=90)
            ce = build_corporate_events_block(events)
            if ce:
                text += "\n📅 <b>Корпоративные события:</b>\n"
                for ev in ce:
                    text += f"• {html_escape(ev)}\n"
    finally:
        _db.close()

    data_advice = _format_data_advice(fused)
    if data_advice:
        text += f"\n{data_advice}"

    text += f"\n\n💡 Доля в портфеле: до {fused.get('max_portfolio_pct', 10)}%"

    chunks = _chunk_text(text, 4096)
    if msg:
        await msg.edit_text(chunks[0], parse_mode="HTML", reply_markup=build_analyze_keyboard(ticker))
    else:
        await update.effective_message.reply_text(chunks[0], reply_markup=build_analyze_keyboard(ticker), parse_mode="HTML")
    for chunk in chunks[1:]:
        await update.effective_message.reply_text(chunk, reply_markup=build_analyze_keyboard(ticker), parse_mode="HTML")


async def _reply_with_allocation(update: Update, capital: float, exclude: set[str] | None = None) -> None:
    if not update.effective_message:
        return
    msg = await update.effective_message.reply_text(f"\U0001f50d Анализирую рынок для {capital:,.0f} ₽...")

    try:
        picks = allocator.recommend(capital=capital, exclude=exclude)
        if not picks:
            await msg.edit_text("Не удалось подобрать варианты. Запустите `finn update` для загрузки данных.")
            return

        text = f"\U0001f4b0 <b>Рекомендации для {capital:,.0f} ₽</b>"
        if exclude:
            text += f" (без {', '.join(sorted(exclude))})"
        text += "\n\n"

        for i, p in enumerate(picks[:10], 1):
            name = p.get("name") or p["ticker"]
            reason = p.get("reason", "")
            last_price = p.get("last_price")
            price_str = f"цена {last_price:.0f} ₽" if last_price else ""
            text += f"{i}. <b>{html_escape(p['ticker'])}</b> ({html_escape(name)}) — {html_escape(p['category'])}\n"
            text += f"   {price_str}\n"
            if reason:
                text += f"   \u2192 {html_escape(reason)}\n"
            risk = p.get("risk", {})
            if risk:
                rparts = []
                if risk.get("var_95"):
                    rparts.append(f"риск падения {risk['var_95']:.1f}%/день")
                if risk.get("stop_loss_pct"):
                    rparts.append(f"стоп-лосс {risk['stop_loss_pct']:.1f}%")
                if risk.get("suggested_shares"):
                    rparts.append(f"макс. {risk['suggested_shares']} шт")
                if rparts:
                    text += f"   {' • '.join(rparts)}\n"
            text += "\n"

        chunks = _chunk_text(text, 4096)
        allocation_text = _format_allocation_plan(picks, capital)
        alloc_chunks = _chunk_text(allocation_text, 4096) if allocation_text else []

        await msg.edit_text(chunks[0], parse_mode="HTML")
        for chunk in chunks[1:]:
            await update.effective_message.reply_text(chunk, parse_mode="HTML")
        for chunk in alloc_chunks:
            await update.effective_message.reply_text(chunk, parse_mode="HTML")
    except Exception:
        logger.exception("Unhandled exception")
        logger.warning("Recommendation error", exc_info=True)
        await msg.edit_text("\u274c Не удалось рассчитать рекомендации. Убедитесь, что запущен `finn update`.")


async def _ask_llm_general(update: Update, text: str, ticker_context: str = "") -> None:
    if not update.effective_message:
        return
    msg = await update.effective_message.reply_text("🤔 Думаю...")
    try:
        from src.llm.router import llm

        user_id = update.effective_user.id if update.effective_user else None
        answer = await llm.answer_question(
            question=text,
            user_id=user_id,
            ticker_context=ticker_context,
        )

        if not answer:
            answer = "Не могу сформулировать ответ. Попробуйте уточнить вопрос или указать тикер через /analyze"

        chunks = _chunk_text(answer, 4096)
        await msg.edit_text(html_escape(chunks[0]), parse_mode="HTML")
        for chunk in chunks[1:]:
            await update.effective_message.reply_text(html_escape(chunk), parse_mode="HTML")
    except Exception:
        logger.exception("Unhandled exception")
        logger.warning("LLM error", exc_info=True)
        await msg.edit_text(
            "Не смог ответить на вопрос. Попробуйте:\n• /analyze SBER — анализ конкретной акции\n• /allocate 50000 — куда вложить деньги"
        )


async def _handle_text(update: Update, text: str) -> None:
    if not update.effective_message:
        return
    amount = _extract_allocation_amount(text)
    if amount is not None:
        exclude = _find_excluded_tickers(text)
        await _reply_with_allocation(update, amount, exclude=exclude)
        return
    tickers = _find_tickers(text)
    if tickers:
        ticker = tickers[0]
        if _is_detailed_question(text, ticker):
            ctx = _build_stock_context(ticker)
            await _ask_llm_general(update, text, ticker_context=ctx)
            return
        if len(tickers) > 1:
            await update.effective_message.reply_text(f"Нашёл несколько, анализирую {ticker}")
        await _reply_with_analysis(update, ticker)
        return
    await _ask_llm_general(update, text)


async def _save_position(update: Update, ticker: str, qty: float, avg_price: float | None = None) -> None:
    if not update.effective_message:
        return
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            await update.effective_message.reply_text(f"Инструмент {ticker} не найден в базе. Запустите `finn update {ticker}`.")
            return
        if avg_price is None:
            price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
            avg_price = float(price.close) if price else 0

        existing = db.query(PortModel).filter_by(instrument_id=inst.id).first()
        if existing:
            existing.quantity += qty
            if existing.avg_price and avg_price:
                total_qty = existing.quantity
                existing.avg_price = float((float(existing.avg_price) * (total_qty - qty) + avg_price * qty) / total_qty)
            db.commit()
            await update.effective_message.reply_text(f"✅ {ticker}: добавлено {qty} шт. (всего {existing.quantity:.1f} шт.)")
        else:
            pos = PortModel(instrument_id=inst.id, quantity=qty, avg_price=avg_price)
            db.add(pos)
            db.commit()
            await update.effective_message.reply_text(f"✅ {ticker}: {qty} шт. добавлено в портфель")
    except Exception:
        logger.exception("Unhandled exception")
        db.rollback()
        logger.warning("Save position error", exc_info=True)
        await update.effective_message.reply_text("❌ Не удалось добавить позицию. Попробуйте позже.")
    finally:
        db.close()
