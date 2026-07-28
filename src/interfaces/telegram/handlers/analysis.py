from collections import OrderedDict
from typing import Any

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.analysis.backtest import backtest_allocation
from src.analysis.market.correlation_analysis import correlation_table
from src.analysis.market.sector import sector_analyzer
from src.analysis.whatif import whatif_macro, whatif_scenario
from src.db.connection import get_session
from src.db.models import GeoRiskScore, Instrument
from src.db.models import Signal as SignalModel
from src.interfaces.telegram.messages import _reply_with_analysis
from src.interfaces.telegram_guard import _check_cooldown, guard
from src.interfaces.telegram_helpers import (
    _chunk_text,
    build_top_keyboard,
    html_escape,
)
from src.portfolio.allocator import allocator

logger = structlog.get_logger(__name__)


@guard()
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.db.connection import get_session
    from src.db.models import DailyReport

    db = get_session()
    try:
        report = db.query(DailyReport).order_by(DailyReport.date.desc()).first()
        if report and report.report_text:
            text = str(report.report_text)
            try:
                await update.effective_message.reply_text(text, parse_mode="HTML")
            except Exception:
                logger.exception("Unhandled exception")
                await update.effective_message.reply_text(text)
        else:
            await update.effective_message.reply_text("Ежедневный отчёт ещё не сформирован. Он появляется после 23:50 МСК.")
    finally:
        db.close()


@guard()
async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("📆 Формирую недельную сводку...")
    try:
        from src.scheduler.reporting import generate_weekly_report_text

        text = await generate_weekly_report_text()
        for chunk in _chunk_text(text, 4096):
            await update.effective_message.reply_text(chunk, parse_mode="HTML")
    except Exception:
        logger.exception("Unhandled exception")
        logger.exception("Weekly report failed")
        await update.effective_message.reply_text("Не удалось сформировать недельную сводку.")


@guard(with_cooldown=True)
async def backtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    amount: float = 100_000
    if context.args:
        try:
            amount = float(context.args[0].replace(" ", "").replace(",", "."))
            if amount < 500:
                await update.effective_message.reply_text("Минимальная сумма — 500 ₽")
                return
        except ValueError:
            logger.debug("Invalid amount argument: %s", context.args[0])

    await update.effective_message.reply_text(f"🕰 Прогоняю стратегию для {amount:,.0f} ₽ за последний год...")
    result = backtest_allocation(capital=amount)
    summary = html_escape(result.summary())
    await update.effective_message.reply_text(summary, parse_mode="HTML")


@guard(with_cooldown=True)
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        signals = db.query(SignalModel).filter_by(instrument_id=inst.id).order_by(SignalModel.date.desc()).limit(60).all()
        if not signals:
            await update.effective_message.reply_text(f"Нет истории сигналов для {ticker}")
            return

        lines = [f"📈 <b>История сигналов — {html_escape(ticker)}</b>\n"]
        for s in reversed(signals):
            emoji = "🟢" if s.action in ("BUY", "CAUTIOUS_BUY") else "🔴" if s.action == "SELL" else "⚪"
            conf = s.confidence or 0
            lines.append(f"{emoji} {s.date}  <b>{html_escape(s.action)}</b> <i>{conf:.0%}</i>")
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()


@guard()
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_cooldown(update):
        return
    args = context.args or []
    ticker = args[0].upper() if args else None
    if not ticker:
        await update.effective_message.reply_text("Укажите тикер: /analyze SBER")
        return
    await _reply_with_analysis(update, ticker)


@guard()
async def sectors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_cooldown(update):
        return

    await update.effective_message.reply_text("🏭 Анализирую сектора...")
    db = get_session()
    try:
        perf = sector_analyzer.compute_sector_performance(db)
        vol = sector_analyzer.compute_sector_volatility(db)
        lines = ["🏭 <b>Доходность секторов (30д):</b>\n"]
        sorted_sectors = sorted(perf.items(), key=lambda x: x[1], reverse=True)
        for sector, perf_val in sorted_sectors:
            emoji = "\U0001f7e2" if perf_val > 0 else "\U0001f534"
            v = vol.get(sector, "")
            vol_str = f" (волат. {v:.0%})" if isinstance(v, float) else ""
            lines.append(f"{emoji} {html_escape(sector)}: {perf_val:+.1%}{vol_str}")

        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()


@guard()
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_cooldown(update):
        return
    await update.effective_message.reply_text("🏆 Ищу лучшие возможности...")
    try:
        picks = await allocator.recommend(capital=100_000)
        if not picks:
            await update.effective_message.reply_text("Нет данных. Запустите `finn update`.")
            return

        from src.db.connection import get_session
        from src.interfaces.response_formatter import (
            build_financial_highlights,
            load_company_profile,
            load_financial_report,
        )

        _db = get_session()
        try:
            categories: OrderedDict[str, list[Any]] = OrderedDict()
            for p in picks:
                cat = p.get("category", "Прочее")
                if cat not in categories:
                    categories[cat] = []
                if len(categories[cat]) < 5:
                    categories[cat].append(p)

            text = "🏆 <b>Топ по категориям:</b>\n\n"
            for cat, items in categories.items():
                text += f"▫️ <b>{html_escape(cat)}</b>\n"
                for i, p in enumerate(items, 1):
                    score = p.get("score", 0)
                    text += f"  {i}. <b>{html_escape(p['ticker'])}</b> — score {score:.2f}\n"
                    reason = p.get("reason", "")
                    if reason:
                        text += f"     → {html_escape(reason[:80])}\n"
                    inst = _db.query(Instrument).filter_by(ticker=p["ticker"]).first()
                    if inst:
                        profile = load_company_profile(_db, inst.id)
                        if profile and profile.description:
                            text += f"     {html_escape(profile.description[:180])}\n"
                        report = load_financial_report(_db, inst.id)
                        fh = build_financial_highlights(report)
                        if fh:
                            text += f"     {html_escape(fh[0])}\n"
                text += "\n"
        finally:
            _db.close()

        await update.effective_message.reply_text(text, reply_markup=build_top_keyboard(), parse_mode="HTML")
    except Exception:
        logger.exception("Unhandled exception")
        logger.warning("Top command error", exc_info=True)
        await update.effective_message.reply_text("\u274c Не удалось загрузить топ. Убедитесь, что запущен `finn update`.")


@guard(with_cooldown=True)
async def geo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            await update.effective_message.reply_text(f"\U0001f30d Геополитический риск: {score.score}/10 ({level})\nДата: {score.date}")
        else:
            await update.effective_message.reply_text("Нет данных. Запустите daily update.")
    finally:
        db.close()


@guard(with_cooldown=True)
async def correlation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tickers = list(context.args) if context.args else None
    text = correlation_table(tickers)
    for chunk in _chunk_text(text, 4096):
        await update.effective_message.reply_text(html_escape(chunk), parse_mode="HTML")


@guard()
async def whatif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        await update.effective_message.reply_text(html_escape(chunk), parse_mode="HTML")
