import structlog
from telegram import Message, Update
from telegram.ext import ContextTypes

from src.interfaces.telegram.handlers import (
    add_start,
    allocate,
    backtest,
    bot_status,
    correlation,
    daily,
    export_portfolio,
    geo,
    history,
    my_authors,
    news,
    pnl,
    portfolio,
    profile,
    rates,
    remove_position,
    report,
    sectors,
    social_cmd,
    start,
    stress,
    subscribe,
    top,
    whatif,
)
from src.interfaces.telegram.messages import _reply_with_analysis, _save_position
from src.interfaces.telegram_guard import _check_access
from src.interfaces.telegram_helpers import (
    TOTAL_PAGES,
    build_main_reply_keyboard,
    build_reply_keyboard,
    format_start_html,
)

logger = structlog.get_logger(__name__)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    if not data:
        return
    parts = data.split(":", 1)
    msg = query.message

    if parts[0] == "analyze" and len(parts) > 1:
        ticker = parts[1]
        if isinstance(msg, Message):
            await msg.reply_text(f"\U0001f50d Анализирую {ticker}...")
        await _reply_with_analysis(update, ticker)

    elif parts[0] == "add" and len(parts) > 1:
        ticker = parts[1]
        await _save_position(update, ticker, 1.0)

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
        elif action == "home":
            if isinstance(msg, Message):
                await msg.reply_text(
                    format_start_html(),
                    reply_markup=build_main_reply_keyboard(),
                    parse_mode="HTML",
                )
        elif action == "news":
            await news(update, context)


async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_message.text:
        return
    text = update.effective_message.text

    if text == "\U000025b6\ufe0f":
        page = context.user_data.get("kb_page", 1) if context.user_data else 1
        next_page = min(page + 1, TOTAL_PAGES)
        if context.user_data is not None:
            context.user_data["kb_page"] = next_page
        await update.effective_message.reply_text(
            f"Страница {next_page}/{TOTAL_PAGES}",
            reply_markup=build_reply_keyboard(next_page),
        )
        return
    if text == "\u25c0\ufe0f":
        page = context.user_data.get("kb_page", 1) if context.user_data else 1
        prev_page = max(page - 1, 1)
        if context.user_data is not None:
            context.user_data["kb_page"] = prev_page
        await update.effective_message.reply_text(
            f"Страница {prev_page}/{TOTAL_PAGES}",
            reply_markup=build_reply_keyboard(prev_page),
        )
        return
    if text.startswith("\U0001f522"):
        return

    if text == "\U0001f50d Анализ":
        await top(update, context)
    elif text == "\U0001f4ca Портфель":
        await portfolio(update, context)
    elif text == "\U0001f3c6 Топ":
        await top(update, context)
    elif text == "\U0001f4f0 Новости":
        await news(update, context)
    elif text == "\U0001f4cb Сводка":
        await daily(update, context)
    elif text == "\U0001f3ed Сектора":
        await sectors(update, context)
    elif text == "\U0001f4b0 Аллокация":
        context.args = []
        await allocate(update, context)
    elif text == "\U0001f9ea Стресс-тест":
        await stress(update, context)
    elif text == "\U0001f504 Корреляция":
        await correlation(update, context)
    elif text == "\u2795 Добавить":
        await add_start(update, context)
    elif text == "\u2796 Удалить":
        await remove_position(update, context)
    elif text == "\U0001f4dc История":
        await history(update, context)
    elif text == "\U0001f4e4 Экспорт CSV":
        await export_portfolio(update, context)
    elif text == "\u23ea Бэктест":
        context.args = ["100000"]
        await backtest(update, context)
    elif text == "\u2699\ufe0f Профиль":
        await profile(update, context)
    elif text == "\U0001f4ca P&L":
        await pnl(update, context)
    elif text == "\U0001f4c4 Отчёт":
        await report(update, context)
    elif text == "\U0001f4b1 Курсы":
        await rates(update, context)
    elif text == "\U0001f465 Авторы":
        await my_authors(update, context)
    elif text == "\U0001f4f0 Соц.сен.":
        context.args = []
        await social_cmd(update, context)
    elif text == "\U0001f30d Гео-риск":
        await geo(update, context)
    elif text == "\U0001f52e What-If":
        await whatif(update, context)
    elif text == "\U0001f4e1 Статус":
        await bot_status(update, context)
    elif text == "\U0001f514 Подписки":
        await subscribe(update, context)
    elif text == "\U0001f3e0 /start":
        await start(update, context)
    elif text == "\U0001f319 Ночн.режим":
        await profile(update, context)
    elif text == "\u2753 Помощь" and update.effective_message:
        await update.effective_message.reply_text(
            format_start_html(),
            reply_markup=build_main_reply_keyboard(),
            parse_mode="HTML",
        )
