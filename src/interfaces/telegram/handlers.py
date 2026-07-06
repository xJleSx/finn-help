import asyncio
import io
import logging
from datetime import date, timedelta
from typing import Any, Optional, cast

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.analysis.backtest import backtest_allocation
from src.analysis.correlation_analysis import correlation_table
from src.analysis.sector import sector_analyzer
from src.analysis.stress import (
    StressTester,
    format_portfolio_for_stress,
)
from src.analysis.whatif import whatif_macro, whatif_scenario
from src.collectors.cbr import CBRCollector
from src.config import personal, settings
from src.db.connection import get_session
from src.db.models import (
    GeoRiskScore,
    Instrument,
    News,
    UserSetting,
)
from src.db.models import Portfolio as PortModel
from src.db.models import Signal as SignalModel
from src.interfaces.telegram_guard import _check_cooldown, guard
from src.interfaces.telegram_helpers import (
    _chunk_text,
    _find_excluded_tickers,
    build_main_reply_keyboard,
    build_top_keyboard,
    format_start_html,
    get_portfolio_positions,
    html_escape,
)
from src.interfaces.telegram.messages import (
    _handle_text,
    _reply_with_allocation,
    _reply_with_analysis,
    _save_position,
)
from src.notifications.service import NotificationService
from src.portfolio.allocator import allocator
from src.reports import generate_portfolio_csv

logger = structlog.get_logger(__name__)


@guard()
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        format_start_html(),
        reply_markup=build_main_reply_keyboard(),
        parse_mode="HTML",
    )


@guard(with_cooldown=True)
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None:
        return
    uid = update.effective_user.id
    cid = update.effective_chat.id
    args = context.args or []
    ntype = args[0] if args else "signal"
    valid_types = frozenset({"signal", "daily", "geo", "dividend", "trade"})
    if ntype not in valid_types:
        await update.effective_message.reply_text(f"Неизвестный тип: {html_escape(ntype)}. Допустимые: {', '.join(sorted(valid_types))}")
        return

    ns = NotificationService()
    try:
        ns.subscribe(uid, cid, ntype)
    except Exception:
        logger.exception("subscribe_failed", user_id=uid, notify_type=ntype)
        await update.effective_message.reply_text("❌ Ошибка при подписке. Попробуйте позже.")
        return
    type_names = {"signal": "сигналы", "daily": "ежедневные сводки", "geo": "гео-риски", "dividend": "дивиденды", "trade": "сделки"}
    await update.effective_message.reply_text(f"✅ Вы подписаны на {type_names.get(ntype, ntype)}")


@guard(with_cooldown=True)
async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    args = context.args or []
    ntype = args[0] if args else None
    if ntype is not None:
        valid_types = frozenset({"signal", "daily", "geo", "dividend", "trade"})
        if ntype not in valid_types:
            await update.effective_message.reply_text(f"Неизвестный тип: {html_escape(ntype)}. Допустимые: {', '.join(sorted(valid_types))}")
            return
    ns = NotificationService()
    try:
        ns.unsubscribe(uid, ntype)
    except Exception:
        logger.exception("unsubscribe_failed", user_id=uid, notify_type=ntype)
        await update.effective_message.reply_text("❌ Ошибка при отписке. Попробуйте позже.")
        return
    if ntype:
        type_names = {"signal": "сигналы", "daily": "ежедневные сводки", "geo": "гео-риски", "dividend": "дивиденды", "trade": "сделки"}
        await update.effective_message.reply_text(f"✅ Подписка на {type_names.get(ntype, ntype)} отменена")
    else:
        await update.effective_message.reply_text("✅ Все подписки отменены")


@guard(with_cooldown=True)
async def subscribe_author(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None:
        return
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Укажите автора: /subscribe_author @name")
        return
    author_nick = args[0].lstrip("@")
    uid = update.effective_user.id
    cid = update.effective_chat.id
    ns = NotificationService()
    try:
        ns.subscribe_author(uid, cid, author_nick)
    except Exception:
        logger.exception("subscribe_author_failed", user_id=uid, author=author_nick)
        await update.effective_message.reply_text("❌ Ошибка при подписке на автора. Попробуйте позже.")
        return
    await update.effective_message.reply_text(f"✅ Вы подписаны на автора @{html_escape(author_nick)}")


@guard(with_cooldown=True)
async def unsubscribe_author(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Укажите автора: /unsubscribe_author @name")
        return
    author_nick = args[0].lstrip("@")
    uid = update.effective_user.id
    ns = NotificationService()
    try:
        ns.unsubscribe_author(uid, author_nick)
    except Exception:
        logger.exception("unsubscribe_author_failed", user_id=uid, author=author_nick)
        await update.effective_message.reply_text("❌ Ошибка при отписке от автора. Попробуйте позже.")
        return
    await update.effective_message.reply_text(f"✅ Отписались от автора @{html_escape(author_nick)}")


@guard(with_cooldown=True)
async def my_authors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    ns = NotificationService()
    authors = ns.get_user_subscribed_authors(uid)
    if not authors:
        await update.effective_message.reply_text(
            "У вас нет подписок на авторов.\nИспользуйте /subscribe_author @name чтобы подписаться.\nСписок доступных авторов: /pulse"
        )
        return
    lines = ["👥 <b>Ваши авторы:</b>\n"]
    for a in authors:
        lines.append(f"• @{html_escape(a)}")
    lines.append("\nЧтобы отписаться: /unsubscribe_author @name")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")


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
        logger.exception("Weekly report failed")
        await update.effective_message.reply_text("Не удалось сформировать недельную сводку.")


@guard(with_cooldown=True)
async def allocate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


@guard(with_cooldown=True)
async def stress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
async def backtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        picks = allocator.recommend(capital=100_000)
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
        logger.warning("Top command error", exc_info=True)
        await update.effective_message.reply_text("\u274c Не удалось загрузить топ. Убедитесь, что запущен `finn update`.")


@guard(with_cooldown=True)
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        db = get_session()
        try:
            rows = db.query(News).order_by(News.published_at.desc().nullslast()).limit(50).all()
            if not rows:
                await update.effective_message.reply_text("Нет новостей.")
                return
            text = "📰 <b>Последние 50 новостей:</b>\n\n"
            for i, n in enumerate(rows, 1):
                title = html_escape((n.title or "")[:120])
                pub = n.published_at.strftime("%d.%m.%Y") if n.published_at else "?"
                src = html_escape(n.source_name or n.source_type or "?")
                sent = f" ({n.sentiment_score:+.2f})" if n.sentiment_score is not None else ""
                text += f"{i}. [{pub}] {title}{sent}\n"
                if n.source_name:
                    text += f"   — {src}\n"
                text += "\n"
            for chunk in _chunk_text(text, 4096):
                await update.effective_message.reply_text(chunk, parse_mode="HTML")
        finally:
            db.close()
    except Exception:
        logger.warning("News command error", exc_info=True)
        await update.effective_message.reply_text("❌ Не удалось загрузить новости.")


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


@guard(with_cooldown=True)
async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.effective_message.reply_text("Задайте вопрос, например: /ask Что думаешь про SBER?")
        return
    await _handle_text(update, text)


async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_message.text:
        return
    await _handle_text(update, update.effective_message.text)


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
        for r in rows:
            qty = r["quantity"]
            avg = r["avg_price"]
            cur = r["current_price"]
            val = r["value"]
            cost = avg * qty
            pnl = val - cost
            pnl_pct = ((cur / avg) - 1) * 100 if avg > 0 else 0.0
            emoji = "🟢" if pnl > 0.5 else ("🔴" if pnl < -0.5 else "⚪")
            pnl_display = "" if abs(pnl) < 0.5 else f"{pnl:+,.2f}"
            pnl_pct_display = "" if abs(pnl_pct) < 0.01 else f"{pnl_pct:+.2f}%"
            if pnl_display and pnl_pct_display:
                pnl_line = f"   P&L: {pnl_display} ₽ ({pnl_pct_display})"
            else:
                pnl_line = "   P&L: ~0 ₽"

            lines.append(
                f"{emoji} <b>{html_escape(r['ticker'])}</b>: {qty:.0f} шт × {cur:.2f} ₽\n   Средняя: {avg:.2f} | Стоимость: {val:,.0f} ₽\n{pnl_line}"
            )
            total_value += val
            total_cost += cost

        total_pnl = total_value - total_cost
        total_pnl_pct = ((total_value / total_cost) - 1) * 100 if total_cost > 0 else 0.0
        total_emoji = "🟢" if total_pnl > 0.5 else ("🔴" if total_pnl < -0.5 else "⚪")
        total_pnl_str = "" if abs(total_pnl) < 0.5 else f"{total_pnl:+,.2f}"
        total_pnl_pct_str = "" if abs(total_pnl_pct) < 0.01 else f"{total_pnl_pct:+.2f}%"
        pnl_suffix = f" | P&L: {total_pnl_str} ₽ ({total_pnl_pct_str})" if total_pnl_str and total_pnl_pct_str else " | P&L: ~0 ₽"
        lines.append(f"\n{total_emoji} <b>Итого:</b> {total_value:,.0f} ₽{pnl_suffix}")
        await msg.edit_text("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()


@guard(with_cooldown=True)
async def remove_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


@guard()
async def social_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    ticker = args[0].upper() if args else None
    if not ticker:
        await update.effective_message.reply_text("Использование: /social TICKER\nПример: /social SBER")
        return

    from src.social.sentiment.aggregator import aggregator

    result = aggregator.get_ticker_sentiment(ticker)
    if result["count"] == 0:
        await update.effective_message.reply_text(f"\U0001f50e Нет social-данных для {ticker}")
        return

    emoji = "\U0001f7e2" if result["score"] > 0.1 else "\U0001f534" if result["score"] < -0.1 else "\U0001f7e1"
    await update.effective_message.reply_text(
        f"{emoji} Social Sentiment — {ticker}\n"
        f"  Score: {result['score']:.3f}\n"
        f"  Расхождение: {result['divergence']:.3f}\n"
        f"  Постов проанализировано: {result['count']}\n"
        f"  Средняя уверенность: {result.get('avg_confidence', 0):.3f}"
    )


@guard()
async def pulse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    author = args[0] if args else None
    if not author:
        from src.config import personal as _personal

        social_sources: dict[str, Any] = cast(dict[str, Any], _personal.get("social_sources", {}))
        pulse_config: dict[str, Any] = cast(dict[str, Any], social_sources.get("pulse", {}))
        authors: list[Any] = cast(list[Any], pulse_config.get("authors", []))
        await update.effective_message.reply_text("Отслеживаемые авторы Пульса:\n" + "\n".join(f"  @{a}" for a in authors))
        return

    from src.social.registry import registry

    registry.build_from_config()
    src = registry.get("pulse")
    if not src:
        await update.effective_message.reply_text("Пульс не настроен")
        return

    stats = await src.fetch_author_stats(author)
    if stats:
        await update.effective_message.reply_text(
            f"📊 @{author}\n  Подписчиков: {stats.get('followers', '?')}\n  Доходность: {stats.get('yield', '?')}%"
        )
    else:
        await update.effective_message.reply_text(f"Не удалось получить данные @{author}")


@guard(with_cooldown=True)
async def rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


@guard()
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_cooldown(update):
        return

    db = get_session()
    try:
        risk_row = db.query(UserSetting).filter_by(key="risk_profile").first()
        current: str = str(risk_row.value) if risk_row else "balanced"

        goal_row = db.query(UserSetting).filter_by(key="goal").first()
        current_goal: float = float(goal_row.value) if goal_row else 0.0

        args = context.args or []

        if args and args[0].lower() in ("conservative", "balanced", "aggressive"):
            new_profile = args[0].lower()
            allocator.set_profile(new_profile)
            if risk_row:
                risk_row.value = str(new_profile)
            else:
                db.add(UserSetting(key="risk_profile", value=new_profile))
            db.commit()
            names = {"conservative": "Консервативный", "balanced": "Сбалансированный", "aggressive": "Агрессивный"}
            await update.effective_message.reply_text(f"✅ Профиль изменён на <b>{names[new_profile]}</b>")
            return

        if args and args[0].lower() == "goal" and len(args) >= 2:
            try:
                new_goal = float(args[1].replace(" ", "").replace(",", "."))
            except ValueError:
                await update.effective_message.reply_text("Укажите сумму: /profile goal 1000000")
                return
            if goal_row:
                goal_row.value = str(new_goal)
            else:
                db.add(UserSetting(key="goal", value=str(new_goal)))
            db.commit()
            await update.effective_message.reply_text(f"🎯 Цель изменена на {new_goal:,.0f} ₽")
            return

        names = {"conservative": "Консервативный", "balanced": "Сбалансированный", "aggressive": "Агрессивный"}
        desc = {
            "conservative": "50% ETF, 25% облигации, 20% дивидендные, 5% рост",
            "balanced": "40% ETF, 30% дивидендные, 20% облигации, 10% рост",
            "aggressive": "40% рост, 25% ETF, 25% дивидендные, 10% облигации",
        }

        portfolio_value = 0.0
        try:
            rows = get_portfolio_positions(db)
            portfolio_value = sum(r["value"] for r in rows)
        except Exception as e:
            logger.debug("Portfolio value calc failed: %s", e)

        p_tickers: list[Any] = cast(list[Any], personal.get("favorite_tickers", []))
        p_horizon: str = cast(str, personal.get("investment_horizon", "medium"))
        horizon_label = {"short": "Краткосрочный", "medium": "Среднесрочный", "long": "Долгосрочный"}

        text = "📊 <b>Личные настройки</b>\n\n"
        text += f"👤 Профиль риска: <b>{names.get(current, current)}</b>\n"
        text += f"💰 Портфель: {portfolio_value:,.0f} ₽\n"
        if current_goal > 0:
            pct = (portfolio_value / current_goal) * 100 if current_goal > 0 else 0
            text += f"🎯 Цель: {current_goal:,.0f} ₽ ({pct:.1f}%)\n"
        else:
            text += "🎯 Цель: не задана\n"
        text += f"📅 Горизонт: {horizon_label.get(p_horizon, p_horizon)}\n"

        if rows:
            sectors: dict[str, float] = {}
            for r in rows:
                sec = r.get("sector", "Прочее")
                sectors[sec] = sectors.get(sec, 0) + r["value"]
            if sectors:
                text += "\n<b>Сектора:</b>\n"
                for sec, val in sorted(sectors.items(), key=lambda x: -x[1]):
                    pct = val / portfolio_value * 100 if portfolio_value > 0 else 0
                    text += f"  • {sec}: {pct:.0f}%\n"

        if p_tickers:
            text += f"\n⭐ Избранные: {', '.join(p_tickers[:10])}\n"

        text += "\n<b>Команды:</b>\n"
        for k, name in names.items():
            text += f"• <code>/profile {k}</code> — {name} ({desc[k]})\n"
        text += "• <code>/profile goal СУММА</code> — установить цель\n"
        await update.effective_message.reply_text(text, parse_mode="HTML")
    finally:
        db.close()


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
        logger.warning("Report error", exc_info=True)
        await msg.edit_text("❌ Ошибка формирования отчёта.")


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


@guard()
async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from datetime import datetime, timezone

    from src.interfaces.telegram.bot import app

    ns = NotificationService()
    signal_subs = len(ns.get_subscribers("signal"))
    daily_subs = len(ns.get_subscribers("daily"))
    dividend_subs = len(ns.get_subscribers("dividend"))

    uptime = ""
    if app and app.updater and app.updater.running:
        uptime = "✅ Бот работает"
    else:
        uptime = "⚠️ Бот не на связи"

    text = (
        f"<b>📡 Статус бота</b>\n\n"
        f"{uptime}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"<b>Подписки:</b>\n"
        f"🔔 Сигналы: {signal_subs}\n"
        f"📋 Сводки: {daily_subs}\n"
        f"💵 Дивиденды: {dividend_subs}\n"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


@guard(with_cooldown=True)
async def channel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    args = context.args or []
    db = get_session()
    try:
        from src.notifications.channels import ALL_CHANNELS, load_preferences, set_preference

        CHANNEL_NAMES = {"telegram": "Telegram", "email": "Email", "web": "Web Push"}

        if not args or args[0] == "status":
            prefs = load_preferences(db, uid)
            lines = ["<b>📨 Каналы уведомлений</b>\n"]
            for ch in ["telegram", "email", "web"]:
                p = prefs.get(ch, {})
                status = "✅" if p.get("enabled", True) else "❌"
                sev = p.get("min_severity", "LOW")
                lines.append(f"{status} <b>{CHANNEL_NAMES.get(ch, ch)}</b> — min {sev}")
            await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

        elif args[0] == "set":
            if len(args) < 3:
                await update.effective_message.reply_text("Использование: /channel set <telegram|email|web> <on|off>")
                return
            ch = args[1].lower()
            if ch not in ALL_CHANNELS:
                await update.effective_message.reply_text(f"Неизвестный канал: {html_escape(ch)}")
                return
            enabled = args[2].lower() == "on"
            set_preference(db, uid, channel=ch, enabled=enabled)
            status = "включён" if enabled else "отключён"
            await update.effective_message.reply_text(f"✅ {CHANNEL_NAMES.get(ch, ch)} {status}")

        elif args[0] == "severity":
            if len(args) < 3:
                await update.effective_message.reply_text("Использование: /channel severity <telegram|email|web> <LOW|MEDIUM|HIGH|CRITICAL>")
                return
            ch = args[1].lower()
            if ch not in ALL_CHANNELS:
                await update.effective_message.reply_text(f"Неизвестный канал: {html_escape(ch)}")
                return
            level = args[2].upper()
            if level not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                await update.effective_message.reply_text("Уровень: LOW, MEDIUM, HIGH или CRITICAL")
                return
            set_preference(db, uid, channel=ch, min_severity=level)
            await update.effective_message.reply_text(
                f"✅ {CHANNEL_NAMES.get(ch, ch)}: мин. уровень <b>{level}</b>",
                parse_mode="HTML",
            )

        else:
            await update.effective_message.reply_text("Команды: /channel status, /channel set <канал> <on|off>, /channel severity <канал> <уровень>")
    except Exception:
        logger.exception("channel_cmd_failed", user_id=uid)
        await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
    finally:
        db.close()


@guard(with_cooldown=True)
async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Укажите тикер: /mute TICKER")
        return
    ticker = args[0].upper()
    db = get_session()
    try:
        from src.alerts.preferences import UserAlertPreferences

        prefs = UserAlertPreferences()
        ok = prefs.mute_ticker(uid, ticker, db_session=db)
        if ok:
            await update.effective_message.reply_text(f"🔇 Тикер <b>{html_escape(ticker)}</b> заглушён", parse_mode="HTML")
        else:
            await update.effective_message.reply_text(f"ℹ️ <b>{html_escape(ticker)}</b> уже заглушён", parse_mode="HTML")
    except Exception:
        logger.exception("mute_failed", user_id=uid, ticker=ticker)
        await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
    finally:
        db.close()


@guard(with_cooldown=True)
async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Укажите тикер: /unmute TICKER")
        return
    ticker = args[0].upper()
    db = get_session()
    try:
        from src.alerts.preferences import UserAlertPreferences

        prefs = UserAlertPreferences()
        ok = prefs.unmute_ticker(uid, ticker, db_session=db)
        if ok:
            await update.effective_message.reply_text(f"🔊 Тикер <b>{html_escape(ticker)}</b> разглушён", parse_mode="HTML")
        else:
            await update.effective_message.reply_text(f"ℹ️ <b>{html_escape(ticker)}</b> не был заглушён", parse_mode="HTML")
    except Exception:
        logger.exception("unmute_failed", user_id=uid, ticker=ticker)
        await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
    finally:
        db.close()


@guard(with_cooldown=True)
async def muted_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    db = get_session()
    try:
        from src.alerts.preferences import UserAlertPreferences

        prefs = UserAlertPreferences()
        tickers = prefs.get_muted_tickers(uid, db_session=db)
        if tickers:
            lines = ["<b>🔇 Заглушённые тикеры</b>"] + [f"• {html_escape(t)}" for t in sorted(tickers)]
            await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
        else:
            await update.effective_message.reply_text("Нет заглушённых тикеров")
    except Exception:
        logger.exception("muted_failed", user_id=uid)
        await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
    finally:
        db.close()


@guard(with_cooldown=True)
async def quiet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    args = context.args or []

    if not args or args[0] == "status":
        db = get_session()
        try:
            from src.alerts.preferences import UserAlertPreferences

            prefs_mgr = UserAlertPreferences()
            prefs = prefs_mgr.get_preferences(uid, db_session=db)
            sh = prefs.get("quiet_hours_start")
            eh = prefs.get("quiet_hours_end")
            if sh and eh:
                await update.effective_message.reply_text(
                    f"🌙 Тихие часы: <b>{html_escape(sh)}</b> — <b>{html_escape(eh)}</b>",
                    parse_mode="HTML",
                )
            else:
                await update.effective_message.reply_text("🌙 Тихие часы не настроены")
        except Exception:
            logger.exception("quiet_status_failed", user_id=uid)
            await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
        finally:
            db.close()
        return

    if args[0] == "off":
        db = get_session()
        try:
            from src.alerts.preferences import UserAlertPreferences

            prefs_mgr = UserAlertPreferences()
            prefs_mgr.set_preferences(uid, db_session=db, quiet_hours_start=None, quiet_hours_end=None)
            await update.effective_message.reply_text("🌙 Тихие часы отключены")
        except Exception:
            logger.exception("quiet_off_failed", user_id=uid)
            await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
        finally:
            db.close()
        return

    if len(args) >= 2:
        start = args[0]
        end = args[1]
        db = get_session()
        try:
            from src.alerts.preferences import UserAlertPreferences

            prefs_mgr = UserAlertPreferences()
            prefs_mgr.set_preferences(uid, db_session=db, quiet_hours_start=start, quiet_hours_end=end)
            await update.effective_message.reply_text(
                f"🌙 Тихие часы: <b>{html_escape(start)}</b> — <b>{html_escape(end)}</b>",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("quiet_set_failed", user_id=uid)
            await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
        finally:
            db.close()
        return

    await update.effective_message.reply_text(
        "Использование: /quiet <HH:MM> <HH:MM> — установить тихие часы\n/quiet off — отключить\n/quiet — показать текущие"
    )


@guard(with_cooldown=True)
async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    args = context.args or []
    db = get_session()
    try:
        from src.db.models import SmartAlertRule

        if not args or args[0] == "list":
            rules = (
                db.query(SmartAlertRule)
                .filter(
                    SmartAlertRule.user_id == uid,
                    SmartAlertRule.rule_type == "price",
                )
                .all()
            )
            if rules:
                lines = ["<b>💰 Price alerts</b>"]
                for r in rules:
                    direction = ">" if r.condition == "gt" else "<" if r.condition == "lt" else r.condition
                    status = "✅" if r.enabled else "❌"
                    name = f" ({html_escape(r.name)})" if r.name else ""
                    lines.append(f"{status} <b>{html_escape(r.ticker)}</b> {direction} {r.threshold}{name}")
                await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
            else:
                await update.effective_message.reply_text("Нет price-алертов. Создайте: /price add TICKER > 250")
            return

        if args[0] == "add":
            if len(args) < 4:
                await update.effective_message.reply_text("Использование: /price add TICKER > 250 [название]\nНапример: /price add SBER > 300")
                return
            ticker = args[1].upper()
            condition = "gt" if args[2] == ">" else "lt" if args[2] == "<" else "gte" if args[2] == ">=" else "lte" if args[2] == "<=" else "eq"
            try:
                threshold = float(args[3])
            except ValueError:
                await update.effective_message.reply_text("Порог должен быть числом")
                return
            name = " ".join(args[4:]) if len(args) > 4 else None
            existing = (
                db.query(SmartAlertRule)
                .filter(
                    SmartAlertRule.user_id == uid,
                    SmartAlertRule.ticker == ticker,
                    SmartAlertRule.rule_type == "price",
                    SmartAlertRule.condition == condition,
                    SmartAlertRule.threshold == threshold,
                )
                .first()
            )
            if existing:
                await update.effective_message.reply_text(f"ℹ️ Такой price-алерт уже существует (id={existing.id})")
                return
            rule = SmartAlertRule(
                user_id=uid,
                name=name,
                rule_type="price",
                ticker=ticker,
                condition=condition,
                threshold=threshold,
                enabled=True,
            )
            db.add(rule)
            db.commit()
            direction = ">" if condition == "gt" else "<" if condition == "lt" else condition
            await update.effective_message.reply_text(
                f"✅ Price-алерт: <b>{html_escape(ticker)}</b> {direction} {threshold}",
                parse_mode="HTML",
            )
            return

        if args[0] == "remove":
            if len(args) < 2:
                await update.effective_message.reply_text("Использование: /price remove <id>")
                return
            try:
                rule_id = int(args[1])
            except ValueError:
                await update.effective_message.reply_text("ID должен быть числом")
                return
            rule = (
                db.query(SmartAlertRule)
                .filter(
                    SmartAlertRule.id == rule_id,
                    SmartAlertRule.user_id == uid,
                    SmartAlertRule.rule_type == "price",
                )
                .first()
            )
            if not rule:
                await update.effective_message.reply_text("Price-алерт не найден")
                return
            db.delete(rule)
            db.commit()
            await update.effective_message.reply_text(f"✅ Price-алерт #{rule_id} удалён")
            return

        if args[0] == "toggle":
            if len(args) < 2:
                await update.effective_message.reply_text("Использование: /price toggle <id>")
                return
            try:
                rule_id = int(args[1])
            except ValueError:
                await update.effective_message.reply_text("ID должен быть числом")
                return
            rule = (
                db.query(SmartAlertRule)
                .filter(
                    SmartAlertRule.id == rule_id,
                    SmartAlertRule.user_id == uid,
                    SmartAlertRule.rule_type == "price",
                )
                .first()
            )
            if not rule:
                await update.effective_message.reply_text("Price-алерт не найден")
                return
            rule.enabled = not rule.enabled
            db.commit()
            status = "включён" if rule.enabled else "отключён"
            await update.effective_message.reply_text(f"✅ Price-алерт #{rule_id} {status}")
            return

        await update.effective_message.reply_text(
            "Команды:\n"
            "/price list — список price-алертов\n"
            "/price add TICKER > 250 [название] — создать\n"
            "/price remove <id> — удалить\n"
            "/price toggle <id> — вкл/выкл"
        )
    except Exception:
        logger.exception("price_cmd_failed", user_id=uid)
        await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
    finally:
        db.close()


@guard(with_cooldown=True)
async def favorite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    args = context.args or []
    subcmd = args[0].lower() if args else "list"

    db = get_session()
    try:
        from src.db.models import Favorite as FavoriteModel
        from src.db.models import Instrument

        if subcmd == "add":
            if len(args) < 2:
                await update.effective_message.reply_text("Укажите тикер: /favorite add SBER")
                return
            ticker = args[1].upper()
            inst = db.query(Instrument).filter_by(ticker=ticker).first()
            if not inst:
                await update.effective_message.reply_text(f"Инструмент {ticker} не найден в БД")
                return
            existing = db.query(FavoriteModel).filter_by(user_id=uid, ticker=ticker).first()
            if existing:
                await update.effective_message.reply_text(f"⭐ {ticker} уже в избранном")
                return
            db.add(FavoriteModel(user_id=uid, ticker=ticker))
            db.commit()
            await update.effective_message.reply_text(f"⭐ {ticker} добавлен в избранное")

        elif subcmd == "remove":
            if len(args) < 2:
                await update.effective_message.reply_text("Укажите тикер: /favorite remove SBER")
                return
            ticker = args[1].upper()
            fav = db.query(FavoriteModel).filter_by(user_id=uid, ticker=ticker).first()
            if not fav:
                await update.effective_message.reply_text(f"{ticker} нет в избранном")
                return
            db.delete(fav)
            db.commit()
            await update.effective_message.reply_text(f"⭐ {ticker} удалён из избранного")

        elif subcmd == "list":
            favs = db.query(FavoriteModel).filter_by(user_id=uid).order_by(FavoriteModel.created_at).all()
            if not favs:
                await update.effective_message.reply_text("У вас нет избранных инструментов.\nДобавьте через /favorite add TICKER")
                return
            lines = ["⭐ <b>Избранное:</b>\n"]
            for f in favs:
                inst = db.query(Instrument).filter_by(ticker=f.ticker).first()
                name = inst.full_name if inst else ""
                lines.append(f"• <b>{f.ticker}</b> — {html_escape(name or '?')}")
            await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

        else:
            await update.effective_message.reply_text(
                "Команды:\n"
                "• /favorite add TICKER — добавить в избранное\n"
                "• /favorite remove TICKER — удалить из избранного\n"
                "• /favorite list — показать избранное"
            )
    except Exception:
        db.rollback()
        logger.exception("favorite_command_error")
        await update.effective_message.reply_text("❌ Ошибка при работе с избранным")
    finally:
        db.close()
