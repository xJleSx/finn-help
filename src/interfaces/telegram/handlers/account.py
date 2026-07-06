from typing import Any, Optional, cast

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.config import personal
from src.db.connection import get_session
from src.db.models import UserSetting
from src.interfaces.telegram_guard import _check_cooldown, guard
from src.interfaces.telegram_helpers import (
    build_main_reply_keyboard,
    format_start_html,
    get_portfolio_positions,
    html_escape,
)
from src.notifications.service import NotificationService
from src.portfolio.allocator import allocator

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
