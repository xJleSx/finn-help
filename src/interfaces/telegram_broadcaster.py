"""Broadcast functions for Telegram notifications."""

import asyncio
import logging
from datetime import date
from typing import Any, Optional

from src.config import settings
from src.db.connection import get_session
from src.db.models import Instrument
from src.db.models import Signal as SignalModel
from src.interfaces.telegram_helpers import html_escape
from src.interfaces.telegram_alerter import AlertNotifier
from src.notifications.service import NotificationService, format_daily_summary_text, format_signal_text
from sqlalchemy import func

logger = logging.getLogger(__name__)

app: Optional[Any] = None


def set_app(bot_app: Any) -> None:
    global app
    app = bot_app


async def _ns_get_subscribers(ns: NotificationService, notify_type: str = "signal") -> list[tuple[int, int]]:
    return await asyncio.to_thread(ns.get_subscribers, notify_type)


async def _ns_get_upcoming_dividends(ns: NotificationService, days_ahead: int = 14) -> list[Any]:
    return await asyncio.to_thread(ns.get_upcoming_dividends, days_ahead)


async def _ns_get_daily_summary(ns: NotificationService) -> Any:
    return await asyncio.to_thread(ns.get_daily_summary)


async def _ns_save_notification(
    ns: NotificationService, uid: int, notify_type: str, text: str, title: str = ""
) -> None:
    await asyncio.to_thread(ns.save_notification, uid, notify_type, text, title)


async def broadcast_signal(n: Any) -> None:
    if app is None:
        logger.warning("Bot not running, skipping signal broadcast")
        return

    ns = NotificationService()
    text = format_signal_text(n)
    subscribers = await _ns_get_subscribers(ns, "signal")
    for uid, cid in subscribers:
        try:
            await app.bot.send_message(chat_id=uid, text=html_escape(text), parse_mode="HTML")
            await _ns_save_notification(ns, uid, "signal", text, title=n.ticker)
        except Exception as e:
            logger.warning(f"Failed to send signal to {uid}: {e}")


async def broadcast_dividends() -> None:
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
                f"💵 <b>{html_escape(d.ticker)}</b> — дивиденды {d.amount:.0f} ₽/акц"
                + (f" ({d.yield_pct:.1f}%)" if d.yield_pct else "")
                + (f"\n📅 Дивидендная отсечка: {d.ex_date}" if d.ex_date else "")
            )
            try:
                await app.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
                await _ns_save_notification(ns, uid, "dividend", text, title=d.ticker)
            except Exception as e:
                logger.warning(f"Failed to send dividend to {uid}: {e}")


async def broadcast_daily_summary() -> None:
    if app is None:
        logger.warning("Bot not running, skipping daily summary broadcast")
        return

    ns = NotificationService()
    summary = await _ns_get_daily_summary(ns)
    text = format_daily_summary_text(summary)
    subscribers = await _ns_get_subscribers(ns, "daily")
    for uid, cid in subscribers:
        try:
            await app.bot.send_message(chat_id=uid, text=html_escape(text), parse_mode="HTML")
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
) -> None:
    if app is None:
        logger.warning("Bot not running, skipping trade broadcast")
        return

    emoji = "🟢" if direction == "BUY" else "🔴"
    text = f"{emoji} <b>{html_escape(ticker)}</b> — {direction} {quantity} шт. по {price:.2f} ₽\nСтатус: {html_escape(status)}"
    if reason:
        text += f"\n📌 Причина: {html_escape(reason)}"
    if order_id:
        text += f"\n🆔 Заявка: <code>{html_escape(order_id[:12])}...</code>"
    if portfolio_value is not None:
        text += f"\n💵 Портфель: {portfolio_value:,.0f} ₽"

    ns = NotificationService()
    for uid, cid in ns.get_subscribers("trade"):
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            ns.save_notification(uid, "trade", text, title=ticker)
        except Exception as e:
            logger.warning(f"Failed to send trade to {uid}: {e}")


async def broadcast_enrichment_alerts() -> None:
    if app is None:
        logger.warning("Bot not running, skipping alert broadcast")
        return

    from src.alerts.generators import generate_all_alerts, store_alerts

    db = get_session()
    try:
        alerts = generate_all_alerts(db)
        stored = store_alerts(db, alerts)
        if stored:
            logger.info("Enrichment alerts broadcast: %d new", stored)

        notifier = AlertNotifier(app.bot)
        ns = NotificationService()
        subscribers = ns.get_subscribers("signal")
        if not subscribers:
            return
        for uid, cid in subscribers:
            for a in alerts:
                if a["severity"] < 0.4:
                    continue
                await notifier.send_alert(a, chat_id=uid)
    finally:
        db.close()


async def broadcast_author_posts() -> None:
    if app is None:
        logger.warning("Bot not running, skipping author post broadcast")
        return

    from datetime import datetime, timezone

    from src.config import settings
    from src.db.models import SocialPost
    from src.social.pulse import PulseAdapter

    ns = NotificationService()
    db = get_session()
    try:
        cfg_authors = getattr(settings, "pulse_authors", None)
        pulse = PulseAdapter(authors=cfg_authors or [])
        try:
            for nick in (cfg_authors or []):
                subscribers = ns.get_author_subscribers(nick)
                if not subscribers:
                    continue
                recent = db.query(SocialPost).filter_by(author_nick=nick).order_by(SocialPost.published_at.desc()).first()
                since = recent.published_at if recent else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
                posts = await pulse.fetch_author_posts(nick, since=since)
                if not posts:
                    continue
                for uid, cid in subscribers:
                    for post in posts[:3]:
                        text = (
                            f"👤 <b>@{html_escape(nick)}</b>\n"
                            f"{html_escape(post.text[:300])}"
                        )
                        try:
                            await app.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
                        except Exception as e:
                            logger.warning("Failed to send author post to %d: %s", uid, e)
        finally:
            await pulse.close()
    finally:
        db.close()


async def broadcast_today_signals() -> None:
    if app is None:
        logger.warning("Bot not running, skipping signal broadcast")
        return

    db = get_session()
    try:
        signals = (
            db.query(SignalModel)
            .filter(func.date(SignalModel.date) == date.today())
            .order_by(SignalModel.confidence.desc())
            .limit(20)
            .all()
        )
        if not signals:
            return

        ns = NotificationService()
        subscribers = ns.get_subscribers("signal")
        if not subscribers:
            return

        text_parts = ["📊 <b>Свежие сигналы на сегодня:</b>\n"]
        for s in signals:
            inst = db.query(Instrument).filter_by(id=s.instrument_id).first()
            ticker = inst.ticker if inst else "?"
            emoji = "🟢" if s.action in ("BUY", "CAUTIOUS_BUY") else "🔴" if s.action == "SELL" else "⚪"
            conf = s.confidence or 0
            text_parts.append(f"{emoji} <b>{ticker}</b>: {s.action} ({conf:.0%})")
        text = "\n".join(text_parts)

        for uid, cid in subscribers:
            try:
                await app.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            except Exception as e:
                logger.warning("Failed to send signal broadcast to %d: %s", uid, e)
    finally:
        db.close()
