import asyncio
import logging
from datetime import datetime, timezone

from src.scheduler.tasks import daily_update

logger = logging.getLogger(__name__)

UPDATE_INTERVAL = 300  # 5 min (aggressive 24h mode)

_running = False


async def _send_hourly_notification(start: datetime):
    try:
        from src.db.connection import get_session
        from src.db.models import Notification as NotificationModel
        from src.db.models import Price
        from src.db.models import Signal as SignalModel

        db = get_session()
        try:
            since = start.astimezone()
            new_prices = db.query(Price).filter(Price.date >= since.date()).count()
            new_signals = db.query(SignalModel).filter(SignalModel.created_at >= since).count()
            new_notifications = db.query(NotificationModel).filter(
                NotificationModel.created_at >= since
            ).count()

            summary_lines = [
                f"🔄 *Обновление {since.strftime('%H:%M')}*",
                f"   Цены: +{new_prices} записей",
                f"   Сигналы: {new_signals} новых",
                f"   Уведомления: {new_notifications}",
            ]

            text = "\n".join(summary_lines)

            from src.interfaces.telegram import app as bot_app

            if bot_app is not None:
                from src.notifications.service import NotificationService

                ns = NotificationService()
                for uid, cid in ns.get_subscribers("daily"):
                    target_chat = cid or uid
                    try:
                        await bot_app.bot.send_message(chat_id=target_chat, text=text, parse_mode="Markdown")
                    except Exception as e:
                        logger.warning("Failed to send hourly notification to chat %d: %s", target_chat, e)
            else:
                logger.info("Hourly summary:\n%s", text)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to prepare hourly notification: %s", e)


async def run_forever(interval: int = UPDATE_INTERVAL):
    global _running
    if _running:
        logger.warning("Scheduler already running")
        return
    _running = True

    logger.info("Scheduler started (interval=%ds)", interval)
    while _running:
        start = datetime.now(timezone.utc)
        try:
            logger.info("Hourly update started at %s", start.isoformat())
            await daily_update()
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            logger.info("Hourly update finished in %.0fs", elapsed)
            await _send_hourly_notification(start)
        except Exception as e:
            logger.error("Hourly update failed: %s", e, exc_info=True)
            try:
                from src.interfaces.telegram import app as bot_app

                if bot_app is not None:
                    from src.notifications.service import NotificationService

                    ns = NotificationService()
                    for uid, cid in ns.get_subscribers("daily"):
                        target_chat = cid or uid
                        try:
                            await bot_app.bot.send_message(
                                chat_id=target_chat,
                                text=f"⚠️ *Ошибка обновления*: {e}",
                                parse_mode="Markdown",
                            )
                        except Exception:
                            pass
            except Exception:
                pass

        await asyncio.sleep(interval)


async def start_background() -> "asyncio.Task[None]":
    """Start the scheduler as a background task. Returns the task handle."""
    task = asyncio.create_task(run_forever())
    logger.info("Scheduler background task created")
    return task


def stop() -> None:
    global _running
    _running = False
    logger.info("Scheduler stopping")
