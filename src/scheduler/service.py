import asyncio
from datetime import date, datetime, timezone

import structlog
from src.scheduler.reporting import generate_daily_report, take_snapshot
from src.scheduler.tasks import daily_update, weekly_update

_SMART_RULES_CYCLE = 0

logger = structlog.get_logger(__name__)

UPDATE_INTERVAL = 300  # 5 min (aggressive 24h mode)

_running = False

_MSK_OFFSET = 3 * 3600  # MSK = UTC+3


def _msk_now() -> datetime:
    now = datetime.now(timezone.utc)
    ts = now.timestamp() + _MSK_OFFSET
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _retry_failed_receipts() -> None:
    from src.db.connection import get_session
    db = get_session()
    try:
        from src.notifications.retry import ReceiptManager
        mgr = ReceiptManager(db)
        pending = mgr.get_pending_retries(limit=20)
        if not pending:
            return
        logger.info("Retrying %d failed receipts", len(pending))
        for receipt in pending:
            try:
                if receipt.channel == "email" and receipt.title:
                    from src.notifications.channels import EmailPushChannel
                    from src.notifications.channels import PushMessage
                    channel = EmailPushChannel(db=db)
                    msg = PushMessage(
                        title=receipt.title or "",
                        body=receipt.message or "",
                        ticker="",
                        priority=0,
                        alert_type=receipt.notification_type or "general",
                    )
                    success = channel.send("", msg)
                    if success:
                        mgr.mark_sent(receipt.id)
                    else:
                        mgr.mark_failed(receipt.id, "send returned False")
            except Exception as exc:
                logger.exception("receipt_retry_failed", receipt_id=receipt.id)
                mgr.mark_failed(receipt.id, str(exc)[:500], schedule_retry=True)
    except Exception:
        logger.exception("retry_failed_receipts_crashed")
    finally:
        db.close()


def _check_smart_rules() -> None:
    from src.db.connection import get_session
    db = get_session()
    try:
        from src.alerts.smart import SmartAlertEngine
        from src.alerts.history import AlertHistory
        engine = SmartAlertEngine()
        triggered = engine.evaluate_rules(db)
        if triggered:
            history = AlertHistory(db=db)
            for alert in triggered:
                history.log_alert(alert)
            logger.info("Smart rules triggered %d alerts", len(triggered))
    except Exception:
        logger.exception("smart_rules_check_failed")
    finally:
        db.close()


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


async def run_forever(interval: int = UPDATE_INTERVAL) -> None:
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

            global _SMART_RULES_CYCLE
            _SMART_RULES_CYCLE += 1
            if _SMART_RULES_CYCLE % 6 == 0:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, _check_smart_rules)
                except Exception as e:
                    logger.error("Smart rule check failed: %s", e)
                try:
                    await loop.run_in_executor(None, _retry_failed_receipts)
                except Exception as e:
                    logger.error("Receipt retry failed: %s", e)
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
                                        chat_id=target, text=report.report_text, parse_mode="HTML"
                                    )
                                except Exception as e:
                                    logger.warning("Failed to send daily report to %d: %s", target, e)
                        else:
                            logger.info("Daily report:\n%s", report.report_text)

                    # Broadcast fresh signals to subscribers
                    from src.interfaces.telegram_broadcaster import broadcast_today_signals

                    await broadcast_today_signals()

                    # Broadcast upcoming dividends
                    from src.interfaces.telegram_broadcaster import broadcast_dividends

                    await broadcast_dividends()

                    # Broadcast enrichment alerts
                    from src.interfaces.telegram_broadcaster import broadcast_enrichment_alerts

                    await broadcast_enrichment_alerts()

                    # Broadcast new posts from subscribed Pulse authors
                    from src.interfaces.telegram_broadcaster import broadcast_author_posts

                    await broadcast_author_posts()
                except Exception as e:
                    logger.error("Daily snapshot/report/broadcast failed: %s", e)

            if _is_friday():
                week_num = date.today().isocalendar()[1]
                if _LAST_WEEKLY_WEEK != week_num:
                    _LAST_WEEKLY_WEEK = week_num
                    try:
                        logger.info("Taking weekly snapshot...")
                        await take_snapshot("weekly")
                    except Exception as e:
                        logger.error("Weekly snapshot failed: %s", e)
                    try:
                        logger.info("Running weekly data update...")
                        await weekly_update()
                    except Exception as e:
                        logger.error("Weekly data update failed: %s", e)

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
