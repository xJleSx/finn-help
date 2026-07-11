"""Guard decorator and access control for Telegram bot handlers."""

import importlib
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.config import settings
from src.constants import COOLDOWN_SECONDS

logger = structlog.get_logger(__name__)

analysis_cache: OrderedDict[str, tuple[float, dict[str, Any] | None, str]] = OrderedDict()
_user_cooldowns: dict[int, float] = {}
_cache_lock = threading.Lock()


def _load_allowed_ids() -> set[int]:
    raw = settings.telegram_allowed_ids
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


async def _check_access(update: Update) -> bool:
    allowed = _load_allowed_ids()
    if not allowed:
        return True
    uid = update.effective_user.id if update.effective_user else 0
    if uid in allowed:
        return True
    if update.effective_message:
        await update.effective_message.reply_text("⛔ Доступ запрещён. Ваш Telegram ID не в списке разрешённых.")
    return False


async def _check_cooldown(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    now = time.time()
    with _cache_lock:
        if len(_user_cooldowns) > 1000:
            cutoff = now - 3600
            stale = [k for k, v in _user_cooldowns.items() if v < cutoff]
            for k in stale:
                del _user_cooldowns[k]
        last = _user_cooldowns.get(uid, 0)
        if now - last < COOLDOWN_SECONDS:
            if update.effective_message:
                await update.effective_message.reply_text("⏳ Подождите немного перед следующим запросом.")
            return False
        _user_cooldowns[uid] = now
    return True


def guard(with_cooldown: bool = False):
    """Декоратор: проверка доступа, effective_message, опционально cooldown."""

    def decorator(handler: Callable) -> Callable:
        @wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_access(update):
                return None
            if not update.effective_message:
                return None
            if with_cooldown and not await _check_cooldown(update):
                return None
            return await handler(update, context)

        return wrapper

    return decorator


# Track last message time per user for anti-flood
_last_message_time: dict[int, float] = {}
_ANTI_FLOOD_COOLDOWN = float(importlib.import_module("src.config").settings.telegram_anti_flood_cooldown)
_anti_flood_lock = threading.Lock()


def anti_flood_check(user_id: int) -> bool:
    """Returns True if message should be processed, False if flood detected."""
    import time

    now = time.monotonic()
    with _anti_flood_lock:
        last = _last_message_time.get(user_id, 0.0)
        if now - last < _ANTI_FLOOD_COOLDOWN:
            return False
        _last_message_time[user_id] = now
    return True
