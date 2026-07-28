import asyncio
import logging
from typing import Any, Optional

import structlog
from telegram import BotCommand, Update
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.config import settings
from src.interfaces.telegram.callbacks import button_callback, reply_keyboard_handler
from src.interfaces.telegram.conversations import (
    ALLOC_AMOUNT,
    ALLOC_EXCLUDE,
    ALLOC_PROFILE,
    PRICE,
    QUANTITY,
    TICKER,
    add_cancel,
    add_price,
    add_quantity,
    add_start,
    add_ticker,
    alloc_amount,
    alloc_cancel,
    alloc_exclude,
    alloc_profile,
    alloc_start,
)
from src.interfaces.telegram.handlers import (
    allocate,
    analyze,
    ask,
    backtest,
    bond_detail,
    bonds_list,
    bot_status,
    channel_cmd,
    chat_handler,
    correlation,
    daily,
    export_portfolio,
    favorite,
    geo,
    history,
    mute_cmd,
    muted_cmd,
    my_authors,
    new_bonds,
    news,
    pnl,
    portfolio,
    price_cmd,
    profile,
    pulse,
    quiet_cmd,
    rates,
    remove_position,
    report,
    sectors,
    social_cmd,
    start,
    stress,
    subscribe,
    subscribe_author,
    top,
    unmute_cmd,
    unsubscribe,
    unsubscribe_author,
    weekly,
    whatif,
)
from src.interfaces.telegram.handlers.notifications import (
    benchmark,
    brief,
    buy,
    sell,
    taxreport,
)

logger = structlog.get_logger(__name__)

app: Optional[Application[Any, Any, Any, Any, Any, Any]] = None
_scheduler_task: Optional[asyncio.Task[None]] = None


async def _set_commands(app: Application[Any, Any, Any, Any, Any, Any]) -> None:
    commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("analyze", "Анализ инструмента (тикер)"),
        BotCommand("ask", "Спросить ассистента"),
        BotCommand("top", "Лучшие возможности сейчас"),
        BotCommand("portfolio", "Мой портфель"),
        BotCommand("allocate", "Куда вложить (сумма)"),
        BotCommand("add", "Добавить позицию"),
        BotCommand("remove", "Удалить позицию"),
        BotCommand("history", "История сигналов (тикер)"),
        BotCommand("daily", "Ежедневная сводка"),
        BotCommand("weekly", "Недельная сводка"),
        BotCommand("sectors", "Сектора рынка"),
        BotCommand("stress", "Стресс-тест"),
        BotCommand("backtest", "Бэктест стратегии"),
        BotCommand("correlation", "Корреляция активов"),
        BotCommand("whatif", "Что-если сценарий"),
        BotCommand("news", "Последние новости"),
        BotCommand("rates", "Курсы валют"),
        BotCommand("geo", "Геополитический риск"),
        BotCommand("profile", "Риск-профиль"),
        BotCommand("subscribe", "Подписаться на уведомления"),
        BotCommand("unsubscribe", "Отписаться от уведомлений"),
        BotCommand("export", "CSV-отчёт портфеля"),
        BotCommand("social", "Social sentiment (тикер)"),
        BotCommand("pulse", "Авторы Пульса"),
        BotCommand("report", "Отчёт за 120 дней"),
        BotCommand("pnl", "P&L сводка"),
        BotCommand("subscribe_author", "Подписаться на автора Pulse"),
        BotCommand("unsubscribe_author", "Отписаться от автора Pulse"),
        BotCommand("authors", "Мои подписки на авторов"),
        BotCommand("favorite", "Избранное (add/list/remove)"),
        BotCommand("allocate_interactive", "Интерактивное распределение"),
        BotCommand("status", "Статус бота и подписки"),
        BotCommand("brief", "Утренний брифинг"),
        BotCommand("buy", "Купить (тикер кол-во)"),
        BotCommand("sell", "Продать (тикер кол-во)"),
        BotCommand("benchmark", "Сравнение с рынком"),
        BotCommand("tax", "Налоговый отчёт"),
        BotCommand("help", "Помощь"),
    ]
    try:
        await app.bot.set_my_commands(commands)
    except Exception:
        logger.exception("Unhandled exception")
        logger.warning("Failed to set bot commands", exc_info=True)


def _stop_scheduler() -> None:
    from src.scheduler.service import stop as _sched_stop

    _sched_stop()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла внутренняя ошибка. Попробуйте позже или напишите /start",
        )


async def run_bot() -> None:
    global app, _scheduler_task
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set in .env")
        return

    builder = Application.builder().token(settings.telegram_bot_token)
    if settings.telegram_proxy_url:
        builder.proxy(settings.telegram_proxy_url)
        logger.info("Telegram bot using proxy: %s", settings.telegram_proxy_url)
    app = builder.build()

    from src.interfaces.telegram_broadcaster import set_app

    set_app(app)

    await _set_commands(app)

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("status", bot_status))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("allocate", allocate))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("rates", rates))
    app.add_handler(CommandHandler("geo", geo))
    app.add_handler(CommandHandler("social", social_cmd))
    app.add_handler(CommandHandler("pulse", pulse))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("weekly", weekly))
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
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("export", export_portfolio))
    app.add_handler(CommandHandler("correlation", correlation))
    app.add_handler(CommandHandler("whatif", whatif))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("channel", channel_cmd))
    app.add_handler(CommandHandler("favorite", favorite))
    app.add_handler(CommandHandler("allocate_interactive", alloc_start))
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("allocate_interactive", alloc_start)],
            states={
                ALLOC_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, alloc_amount)],
                ALLOC_EXCLUDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, alloc_exclude)],
                ALLOC_PROFILE: [MessageHandler(filters.TEXT & ~filters.COMMAND, alloc_profile)],
            },
            fallbacks=[CommandHandler("cancel", alloc_cancel)],
        )
    )
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))
    app.add_handler(CommandHandler("muted", muted_cmd))
    app.add_handler(CommandHandler("quiet", quiet_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("subscribe_author", subscribe_author))
    app.add_handler(CommandHandler("unsubscribe_author", unsubscribe_author))
    app.add_handler(CommandHandler("authors", my_authors))
    app.add_handler(CommandHandler("bonds", bonds_list))
    app.add_handler(CommandHandler("bond", bond_detail))
    app.add_handler(CommandHandler("newbonds", new_bonds))
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("benchmark", benchmark))
    app.add_handler(CommandHandler("tax", taxreport))

    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_handler(
        MessageHandler(
            filters.Text(
                [
                    "\U0001f50d Анализ",
                    "\U0001f4ca Портфель",
                    "\U0001f3c6 Топ",
                    "\U0001f4f0 Новости",
                    "\U0001f4cb Сводка",
                    "\U0001f3ed Сектора",
                    "\U0001f4b0 Аллокация",
                    "\U0001f9ea Стресс-тест",
                    "\U0001f504 Корреляция",
                    "\u2795 Добавить",
                    "\u2796 Удалить",
                    "\U0001f4dc История",
                    "\U0001f4e4 Экспорт CSV",
                    "\u23ea Бэктест",
                    "\u2699\ufe0f Профиль",
                    "\U0001f4ca P&L",
                    "\U0001f4c4 Отчёт",
                    "\U0001f4b1 Курсы",
                    "\U0001f465 Авторы",
                    "\U0001f4f0 Соц.сен.",
                    "\U0001f30d Гео-риск",
                    "\U0001f52e What-If",
                    "\U0001f4e1 Статус",
                    "\U0001f514 Подписки",
                    "\U0001f3e0 /start",
                    "\U0001f319 Ночн.режим",
                    "\u2753 Помощь",
                    "\u25c0\ufe0f",
                    "\U000025b6\ufe0f",
                    "\U0001f522 1/3",
                    "\U0001f522 2/3",
                    "\U0001f522 3/3",
                ]
            ),
            reply_keyboard_handler,
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    await app.initialize()
    await app.start()

    from src.scheduler.service import start_background as _start_scheduler

    _scheduler_task = await _start_scheduler()

    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared before polling")
    except Exception as e:
        logger.warning("Failed to clear webhook: %s", e)

    polling_retry_delay = 10
    poll_attempt = 0
    if app is None or app.updater is None:
        raise RuntimeError("Telegram app or updater is None after initialization")
    while True:
        try:
            await app.updater.start_polling()
            poll_attempt = 0
            logger.info("Bot started polling with background scheduler")
            break
        except NetworkError as e:
            poll_attempt += 1
            delay = min(polling_retry_delay * (2 ** (poll_attempt - 1)), 300)
            logger.warning("Telegram polling connection failed (attempt %d): %s — retrying in %ds", poll_attempt, e, delay)
            await asyncio.sleep(delay)

    retry_count = 0
    try:
        while True:
            await asyncio.sleep(30)
            if not app.updater.running:
                retry_count += 1
                delay = min(10 * (2 ** (retry_count - 1)), 300)
                logger.warning("Telegram polling stopped, reconnecting in %ds (attempt %d)", delay, retry_count)
                await asyncio.sleep(delay)
                try:
                    await app.updater.start_polling()
                    retry_count = 0
                    logger.info("Telegram polling reconnected")
                except Exception as e:
                    logger.error("Telegram polling reconnect failed: %s", e)
    except asyncio.CancelledError:
        logger.info("Bot shutting down...")
        _stop_scheduler()
        if _scheduler_task and not _scheduler_task.done():
            _scheduler_task.cancel()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())
