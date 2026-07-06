import structlog
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from src.interfaces.telegram_guard import _check_access, _check_cooldown
from src.interfaces.telegram.messages import _reply_with_allocation, _save_position
from src.portfolio.allocator import allocator

logger = structlog.get_logger(__name__)

TICKER, QUANTITY, PRICE = range(3)

ALLOC_AMOUNT, ALLOC_EXCLUDE, ALLOC_PROFILE = range(10, 13)


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    await update.effective_message.reply_text("Введите <b>тикер</b> инструмента (например, SBER):", parse_mode="HTML")
    return TICKER


async def add_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message or not update.effective_message.text or not context.user_data:
        return ConversationHandler.END
    context.user_data["add_ticker"] = update.effective_message.text.strip().upper()
    await update.effective_message.reply_text("Введите <b>количество</b> (например, 10):", parse_mode="HTML")
    return QUANTITY


async def add_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message or not update.effective_message.text or not context.user_data:
        return ConversationHandler.END
    try:
        qty = float(update.effective_message.text.strip().replace(",", "."))
        context.user_data["add_qty"] = qty
    except ValueError:
        await update.effective_message.reply_text("Количество должно быть числом. Попробуйте ещё раз:", parse_mode="HTML")
        return QUANTITY
    await update.effective_message.reply_text(
        "Введите <b>среднюю цену</b> (или отправьте <code>-</code> для автоматической):",
        parse_mode="HTML",
    )
    return PRICE


async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message or not update.effective_message.text or not context.user_data:
        return ConversationHandler.END
    text = update.effective_message.text.strip()
    if text == "-":
        avg_price = None
    else:
        try:
            avg_price = float(text.replace(",", "."))
        except ValueError:
            await update.effective_message.reply_text("Цена должна быть числом или <code>-</code>. Попробуйте ещё раз:", parse_mode="HTML")
            return PRICE

    ticker = context.user_data.get("add_ticker", "")
    qty = context.user_data.get("add_qty", 0)
    context.user_data.clear()
    await _save_position(update, ticker, qty, avg_price)
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.user_data:
        return ConversationHandler.END
    context.user_data.clear()
    if not update.effective_message:
        return ConversationHandler.END
    await update.effective_message.reply_text("❌ Добавление отменено")
    return ConversationHandler.END


async def alloc_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _check_access(update):
        return ConversationHandler.END
    if not update.effective_message:
        return ConversationHandler.END
    await update.effective_message.reply_text(
        "💰 Введите сумму для распределения (например, 100000):",
    )
    return ALLOC_AMOUNT


async def alloc_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message or not update.effective_message.text or not context.user_data:
        return ConversationHandler.END
    text = update.effective_message.text.strip().replace(" ", "").replace(",", ".")
    try:
        amount = float(text)
        if amount < 500:
            await update.effective_message.reply_text("Минимальная сумма — 500 ₽. Попробуйте ещё раз:")
            return ALLOC_AMOUNT
        context.user_data["alloc_amount"] = amount
    except ValueError:
        await update.effective_message.reply_text("Введите число, например 100000:")
        return ALLOC_AMOUNT

    await update.effective_message.reply_text("Какие тикеры исключить? (через пробел, или отправьте «-» чтобы продолжить)\nНапример: GAZP SBER")
    return ALLOC_EXCLUDE


async def alloc_exclude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message or not update.effective_message.text or not context.user_data:
        return ConversationHandler.END
    text = update.effective_message.text.strip()
    if text and text != "-":
        exclude = set(t.upper() for t in text.split())
        context.user_data["alloc_exclude"] = exclude
    else:
        context.user_data["alloc_exclude"] = set()

    await update.effective_message.reply_text(
        "Какой риск-профиль?\n"
        "• <b>conservative</b> — консервативный\n"
        "• <b>balanced</b> — сбалансированный (по умолчанию)\n"
        "• <b>aggressive</b> — агрессивный\n\n"
        "Отправьте профиль или «-» для умолчания:",
        parse_mode="HTML",
    )
    return ALLOC_PROFILE


async def alloc_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message or not update.effective_message.text or not context.user_data:
        return ConversationHandler.END
    text = update.effective_message.text.strip().lower()
    if text in ("conservative", "balanced", "aggressive"):
        context.user_data["alloc_profile"] = text
    else:
        context.user_data["alloc_profile"] = "balanced"

    amount = context.user_data.get("alloc_amount", "100000")
    exclude = context.user_data.get("alloc_exclude", set())
    profile = context.user_data.get("alloc_profile", "balanced")

    allocator.set_profile(profile)
    await _reply_with_allocation(update, amount, exclude=exclude)
    context.user_data.clear()
    return ConversationHandler.END


async def alloc_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data:
        context.user_data.clear()
    if update.effective_message:
        await update.effective_message.reply_text("❌ Распределение отменено")
    return ConversationHandler.END
