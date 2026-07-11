import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.db.connection import get_session
from src.interfaces.telegram.messages import _handle_text
from src.interfaces.telegram_guard import guard
from src.interfaces.telegram_helpers import html_escape
from src.notifications.service import NotificationService

logger = structlog.get_logger(__name__)


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
async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from datetime import datetime, timezone

    from src.interfaces.telegram.bot import app

    ns = NotificationService()
    signal_subs = len(ns.get_subscribers("signal"))
    daily_subs = len(ns.get_subscribers("daily"))
    dividend_subs = len(ns.get_subscribers("dividend"))

    uptime = ""
    uptime = "✅ Бот работает" if app and app.updater and app.updater.running else "⚠️ Бот не на связи"

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

        channel_names = {"telegram": "Telegram", "email": "Email", "web": "Web Push"}

        if not args or args[0] == "status":
            prefs = load_preferences(db, uid)
            lines = ["<b>📨 Каналы уведомлений</b>\n"]
            for ch in ["telegram", "email", "web"]:
                p = prefs.get(ch, {})
                status = "✅" if p.get("enabled", True) else "❌"
                sev = p.get("min_severity", "LOW")
                lines.append(f"{status} <b>{channel_names.get(ch, ch)}</b> — min {sev}")
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
            await update.effective_message.reply_text(f"✅ {channel_names.get(ch, ch)} {status}")

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
                f"✅ {channel_names.get(ch, ch)}: мин. уровень <b>{level}</b>",
                parse_mode="HTML",
            )

        else:
            await update.effective_message.reply_text("Команды: /channel status, /channel set <канал> <on|off>, /channel severity <канал> <уровень>")
    except Exception:
        logger.exception("Unhandled exception")
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
        logger.exception("Unhandled exception")
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
        logger.exception("Unhandled exception")
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
        logger.exception("Unhandled exception")
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
            logger.exception("Unhandled exception")
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
            logger.exception("Unhandled exception")
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
            logger.exception("Unhandled exception")
            logger.exception("quiet_set_failed", user_id=uid)
            await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
        finally:
            db.close()
        return

    await update.effective_message.reply_text(
        "Использование: /quiet <HH:MM> <HH:MM> — установить тихие часы\n/quiet off — отключить\n/quiet — показать текущие"
    )
