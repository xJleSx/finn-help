import asyncio
import logging
from datetime import date, datetime, timezone

from src.scheduler.tasks import daily_update, generate_daily_report, take_snapshot

logger = logging.getLogger(__name__)

UPDATE_INTERVAL = 300  # 5 min (aggressive 24h mode)

_running = False

_MSK_OFFSET = 3 * 3600  # MSK = UTC+3


def _msk_now() -> datetime:
    now = datetime.now(timezone.utc)
    ts = now.timestamp() + _MSK_OFFSET
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _is_time(hour: int, minute: int) -> bool:
    now = _msk_now()
    return now.hour == hour and now.minute == minute


def _is_friday() -> bool:
    return _msk_now().weekday() == 4  # Friday


def _is_first_of_month() -> bool:
    return _msk_now().day == 1


_LAST_SNAPSHOT_DAY: int | None = None
_LAST_WEEKLY_WEEK: int | None = None
_LAST_MONTHLY_MONTH: int | None = None


async def run_forever(interval: int = UPDATE_INTERVAL):
    global _running, _LAST_SNAPSHOT_DAY, _LAST_WEEKLY_WEEK, _LAST_MONTHLY_MONTH
    if _running:
        logger.warning("Scheduler already running")
        return
    _running = True

    logger.info("Scheduler started (interval=%ds)", interval)
    while _running:
        start = datetime.now(timezone.utc)
        try:
            logger.info("Update cycle started at %s", start.isoformat())
            await daily_update()
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            logger.info("Update cycle finished in %.0fs", elapsed)
        except Exception as e:
            logger.error("Update cycle failed: %s", e, exc_info=True)

        # Snapshots at 23:50 MSK
        if _is_time(23, 50):
            today_num = date.today().toordinal()

            if _LAST_SNAPSHOT_DAY != today_num:
                _LAST_SNAPSHOT_DAY = today_num
                try:
                    logger.info("Taking daily snapshot...")
                    await take_snapshot("daily")
                    logger.info("Generating daily report...")
                    report = await generate_daily_report()
                    if report and report.report_text:
                        from src.interfaces.telegram import app as bot_app
                        if bot_app is not None:
                            from src.notifications.service import NotificationService
                            ns = NotificationService()
                            for uid, cid in ns.get_subscribers("daily"):
                                target = cid or uid
                                try:
                                    await bot_app.bot.send_message(
                                        chat_id=target, text=report.report_text, parse_mode="Markdown"
                                    )
                                except Exception as e:
                                    logger.warning("Failed to send daily report to %d: %s", target, e)
                        else:
                            logger.info("Daily report:\n%s", report.report_text)
                except Exception as e:
                    logger.error("Daily snapshot/report failed: %s", e)

            if _is_friday():
                week_num = date.today().isocalendar()[1]
                if _LAST_WEEKLY_WEEK != week_num:
                    _LAST_WEEKLY_WEEK = week_num
                    try:
                        logger.info("Taking weekly snapshot...")
                        await take_snapshot("weekly")
                    except Exception as e:
                        logger.error("Weekly snapshot failed: %s", e)

            if _is_first_of_month():
                month_key = date.today().year * 12 + date.today().month
                if _LAST_MONTHLY_MONTH != month_key:
                    _LAST_MONTHLY_MONTH = month_key
                    try:
                        logger.info("Taking monthly snapshot...")
                        await take_snapshot("monthly")
                    except Exception as e:
                        logger.error("Monthly snapshot failed: %s", e)

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
