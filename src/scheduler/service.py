import asyncio
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import structlog

from src.core.executor import get_executor
from src.scheduler.reporting import generate_daily_report, take_snapshot
from src.scheduler.tasks import daily_update, weekly_update


def _acquire_instance_lock(name: str = "scheduler") -> bool:
    # WARNING: PID-based file lock does NOT work in distributed environments (K8s, multi-replica).
    # Use a DB-based lock or Redis lock for production HA deployments.
    lock_dir = Path(os.environ.get("FINN_LOCK_DIR", tempfile.gettempdir()))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"finn_{name}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Check if stale (PID no longer exists)
        try:
            old_pid = int(lock_path.read_text().strip())
            if old_pid > 0:
                try:
                    os.kill(old_pid, 0)
                except OSError:
                    lock_path.unlink(missing_ok=True)
                    return _acquire_instance_lock(name)
        except (ValueError, OSError):
            logger.warning("Could not acquire instance lock: %s", lock_path)
        return False


def _release_instance_lock(name: str = "scheduler") -> None:
    lock_dir = Path(os.environ.get("FINN_LOCK_DIR", tempfile.gettempdir()))
    lock_path = lock_dir / f"finn_{name}.lock"
    lock_path.unlink(missing_ok=True)


_INSTANCE_LOCK_HELD = False
_SMART_RULES_CYCLE = 0

logger = structlog.get_logger(__name__)

UPDATE_INTERVAL = 300  # 5 min (aggressive 24h mode)

# Architecture reference:
#   - docs/ARCHITECTURE.md — scheduler overview
#   - docs/FinAdvisor_Technical_Documentation.docx — daily/weekly cycle spec
#   - src/tasks/__init__.py — Celery beat schedule definitions
#   - src/scheduler/tasks.py — daily_update / weekly_update implementations

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
                to_email = getattr(receipt, "to_email", None)
                import re as _re
                if receipt.channel == "email" and receipt.title and to_email and _re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+$", to_email):
                    from src.notifications.channels import EmailPushChannel, PushMessage

                    channel = EmailPushChannel(db=db)
                    msg = PushMessage(
                        title=receipt.title or "",
                        body=receipt.message or "",
                        ticker="",
                        priority=0,
                        alert_type=receipt.notification_type or "general",
                    )
                    success = channel.send(to_email, msg)
                    if success:
                        mgr.mark_sent(receipt.id)
                    else:
                        mgr.mark_failed(receipt.id, "send returned False")
            except Exception as exc:
                logger.exception("receipt_retry_failed", receipt_id=receipt.id)
                mgr.mark_failed(receipt.id, str(exc)[:500], schedule_retry=True)
    except Exception:
        logger.exception("Unhandled exception")
        logger.exception("retry_failed_receipts_crashed")
    finally:
        db.close()


def _check_smart_rules() -> None:
    from src.db.connection import get_session

    db = get_session()
    try:
        from src.alerts.history import AlertHistory
        from src.alerts.smart import SmartAlertEngine

        engine = SmartAlertEngine()
        triggered = engine.evaluate_rules(db)
        if triggered:
            history = AlertHistory(db=db)
            for alert in triggered:
                history.log_alert(alert)
            logger.info("Smart rules triggered %d alerts", len(triggered))
    except Exception:
        logger.exception("Unhandled exception")
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
_LAST_BRIEF_DAY: int | None = None
_LAST_COUPON_CHECK_DAY: int | None = None
_LAST_RATING_CHECK_DAY: int | None = None
_LAST_BENCHMARK_WEEK: int | None = None
_LAST_TAX_MONTH: int | None = None
_LAST_PURCHASE_PLAN_DAY: int | None = None
_LAST_DRAWDOWN_CHECK: float = 0.0

_NOTIFICATION_LAST_SENT: dict[str, float] = {}
_QUIET_MODE_ENABLED = True
QUIET_START_HOUR = 23
QUIET_END_HOUR = 9


def _is_quiet_time() -> bool:
    if not _QUIET_MODE_ENABLED:
        return False
    hour = _msk_now().hour
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def _can_send_now(notify_type: str, min_interval: float = 1800.0) -> bool:
    last_sent = _NOTIFICATION_LAST_SENT.get(notify_type, 0.0)
    now = _msk_now().timestamp()
    if now - last_sent < min_interval:
        return False
    _NOTIFICATION_LAST_SENT[notify_type] = now
    return True


async def _send_notification(text: str, notify_type: str = "general", min_interval: float = 1800.0) -> None:
    if _is_quiet_time() and notify_type not in ("redemption", "default"):
        logger.info("Quiet mode: skipping notification %s", notify_type)
        return
    if not _can_send_now(notify_type, min_interval):
        logger.info("Throttled: skipping notification %s (interval %.0fs)", notify_type, min_interval)
        return
    from src.interfaces.telegram import app as bot_app
    if bot_app is None:
        logger.info("Notification (%s):\n%s", notify_type, text)
        return
    from src.notifications.service import NotificationService
    ns = NotificationService()
    for uid, cid in ns.get_subscribers(notify_type):
        chat_id = cid
        if not chat_id:
            from src.db.connection import get_session
            from src.db.models import Subscription
            db = get_session()
            try:
                sub = db.query(Subscription).filter_by(user_id=uid).first()
                chat_id = sub.chat_id if sub else None
            finally:
                db.close()
        if not chat_id:
            logger.warning("No chat_id for user %d, skipping %s", uid, notify_type)
            continue
        try:
            await bot_app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            logger.warning("Failed to send %s to chat %d: %s", notify_type, chat_id, e)


async def run_forever(interval: int = UPDATE_INTERVAL) -> None:
    global _running, _LAST_SNAPSHOT_DAY, _LAST_WEEKLY_WEEK, _LAST_MONTHLY_MONTH, _INSTANCE_LOCK_HELD
    global _LAST_BRIEF_DAY, _LAST_COUPON_CHECK_DAY, _LAST_RATING_CHECK_DAY, _LAST_DRAWDOWN_CHECK
    global _LAST_BENCHMARK_WEEK, _LAST_PURCHASE_PLAN_DAY, _LAST_TAX_MONTH
    if not _acquire_instance_lock("scheduler"):
        logger.error("Another scheduler instance is already running (lock file exists)")
        return
    _INSTANCE_LOCK_HELD = True
    if _running:
        logger.warning("Scheduler already running")
        return
    _running = True

    logger.info("Scheduler started (interval=%ds)", interval)
    shutdown_event = asyncio.Event()

    try:
        from src.core.shutdown import register_shutdown_hook, setup_signal_handlers

        setup_signal_handlers()
        register_shutdown_hook(stop)
    except Exception as e:
        logger.error("Failed to set up signal handlers: %s", e)

    async def _check_shutdown() -> None:
        global _running
        while _running:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if shutdown_event.is_set():
                logger.info("shutdown.scheduler_signal_received")
                _running = False
                break

    asyncio.create_task(_check_shutdown())
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
                    await loop.run_in_executor(get_executor(), _check_smart_rules)
                except Exception as e:
                    logger.error("Smart rule check failed: %s", e)
                try:
                    await loop.run_in_executor(get_executor(), _retry_failed_receipts)
                except Exception as e:
                    logger.error("Receipt retry failed: %s", e)
        except Exception as e:
            logger.error("Update cycle failed: %s", e, exc_info=True)

        # Snapshots at 23:50 MSK
        if _is_time(23, 50):
            today_num = date.today().toordinal()

            if today_num != _LAST_SNAPSHOT_DAY:
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
                                chat_id = cid
                                if not chat_id:
                                    from src.db.connection import get_session
                                    from src.db.models import Subscription
                                    db = get_session()
                                    try:
                                        sub = db.query(Subscription).filter_by(user_id=uid).first()
                                        chat_id = sub.chat_id if sub else None
                                    finally:
                                        db.close()
                                if not chat_id:
                                    logger.warning("No chat_id for user %d, skipping daily report", uid)
                                    continue
                                try:
                                    await bot_app.bot.send_message(chat_id=chat_id, text=report.report_text, parse_mode="HTML")
                                except Exception as e:
                                    logger.warning("Failed to send daily report to chat %d: %s", chat_id, e)
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
                if week_num != _LAST_WEEKLY_WEEK:
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
                if month_key != _LAST_MONTHLY_MONTH:
                    _LAST_MONTHLY_MONTH = month_key
                    try:
                        logger.info("Taking monthly snapshot...")
                        await take_snapshot("monthly")
                    except Exception as e:
                        logger.error("Monthly snapshot failed: %s", e)

            # ── Morning Brief at 9:00 MSK ──────────────────────────────
            if _is_time(9, 0):
                today_num = date.today().toordinal()
                if today_num != _LAST_BRIEF_DAY:
                    _LAST_BRIEF_DAY = today_num
                    try:
                        from src.notifications.morning_brief import build_morning_brief
                        brief_text = await asyncio.to_thread(build_morning_brief)
                        await _send_notification(brief_text, "brief", min_interval=3600)
                    except Exception as e:
                        logger.error("Morning brief failed: %s", e)

            # ── Coupon & Redemption check daily at 10:00 ───────────────
            if _is_time(10, 0):
                today_num = date.today().toordinal()
                if today_num != _LAST_COUPON_CHECK_DAY:
                    _LAST_COUPON_CHECK_DAY = today_num
                    try:
                        from src.notifications.calendar_checker import (
                            format_coupon_alert,
                            format_redemption_alert,
                            get_upcoming_events,
                        )
                        cal = await asyncio.to_thread(get_upcoming_events, 14)
                        for ev in cal.coupons:
                            if ev.days_until in (3, 1, 0):
                                text = format_coupon_alert(ev, ev.days_until)
                                nt = "redemption" if ev.days_until == 0 else "coupon"
                                await _send_notification(text, nt, min_interval=86400)
                        for ev in cal.redemptions:
                            if ev.days_until in (7, 3, 1, 0):
                                text = format_redemption_alert(ev, ev.days_until)
                                await _send_notification(text, "redemption", min_interval=86400)
                    except Exception as e:
                        logger.error("Coupon/redemption check failed: %s", e)

            # ── Rating change check daily at 11:00 ────────────────────
            if _is_time(11, 0):
                today_num = date.today().toordinal()
                if today_num != _LAST_RATING_CHECK_DAY:
                    _LAST_RATING_CHECK_DAY = today_num
                    try:
                        from src.notifications.rating_checker import check_rating_changes, format_rating_alert
                        changes = await asyncio.to_thread(check_rating_changes)
                        for change in changes:
                            text = format_rating_alert(change)
                            await _send_notification(text, "rating", min_interval=86400)
                    except Exception as e:
                        logger.error("Rating check failed: %s", e)

            # ── Drawdown check every 15 min ──────────────────────────
            now_ts = _msk_now().timestamp()
            if now_ts - _LAST_DRAWDOWN_CHECK >= 900:
                _LAST_DRAWDOWN_CHECK = now_ts
                try:
                    from src.notifications.drawdown_checker import check_drawdown, format_drawdown_alert
                    alert = await asyncio.to_thread(check_drawdown)
                    if alert:
                        text = format_drawdown_alert(alert)
                        await _send_notification(text, "drawdown", min_interval=3600)
                except Exception as e:
                    logger.error("Drawdown check failed: %s", e)

            # ── Benchmark comparison (Friday at 12:00) ─────────────────
            if _is_friday() and _is_time(12, 0):
                week_num = date.today().isocalendar()[1]
                if week_num != _LAST_BENCHMARK_WEEK:
                    _LAST_BENCHMARK_WEEK = week_num
                    try:
                        from src.notifications.benchmark_comparison import compare_benchmarks, format_benchmark_comparison
                        cmp = await asyncio.to_thread(compare_benchmarks)
                        if cmp:
                            text = format_benchmark_comparison(cmp)
                            await _send_notification(text, "benchmark", min_interval=86400)
                    except Exception as e:
                        logger.error("Benchmark comparison failed: %s", e)

            # ── Purchase planner (23-24th at 10:00) ───────────────────
            today_day = date.today().day
            if today_day in (23, 24) and _is_time(10, 0):
                day_num = date.today().toordinal()
                if day_num != _LAST_PURCHASE_PLAN_DAY:
                    _LAST_PURCHASE_PLAN_DAY = day_num
                    try:
                        from src.notifications.purchase_planner import format_purchase_plan, generate_purchase_plan
                        plan = await asyncio.to_thread(generate_purchase_plan)
                        if plan:
                            text = format_purchase_plan(plan)
                            await _send_notification(text, "purchase_plan", min_interval=86400)
                    except Exception as e:
                        logger.error("Purchase plan failed: %s", e)

            # ── Tax report (1st of month at 10:00) ────────────────────
            if _is_first_of_month() and _is_time(10, 0):
                month_key = date.today().year * 12 + date.today().month
                if month_key != _LAST_TAX_MONTH:
                    _LAST_TAX_MONTH = month_key
                    try:
                        from src.notifications.tax_report import format_tax_report, generate_tax_report
                        tax_report = await asyncio.to_thread(generate_tax_report)
                        if tax_report:
                            text = format_tax_report(tax_report)
                            await _send_notification(text, "tax", min_interval=86400)
                    except Exception as e:
                        logger.error("Tax report failed: %s", e)

        await asyncio.sleep(interval)


async def start_background() -> "asyncio.Task[None]":
    """Start the scheduler as a background task. Returns the task handle."""
    task = asyncio.create_task(run_forever())
    logger.info("Scheduler background task created")
    return task


def stop() -> None:
    global _INSTANCE_LOCK_HELD
    if _INSTANCE_LOCK_HELD:
        _release_instance_lock("scheduler")
        _INSTANCE_LOCK_HELD = False
    global _running
    _running = False
    logger.info("Scheduler stopping")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_later(2, lambda: None)
    except RuntimeError:
        logger.debug("No event loop available during scheduler stop")
