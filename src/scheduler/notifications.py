import asyncio
from datetime import datetime, timezone

import structlog

from src.scheduler.tasks import weekly_update

logger = structlog.get_logger(__name__)

_MSK_OFFSET = 3 * 3600


def _msk_now() -> datetime:
    now = datetime.now(timezone.utc)
    ts = now.timestamp() + _MSK_OFFSET
    return datetime.fromtimestamp(ts, tz=timezone.utc)


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


async def send_notification(text: str, notify_type: str = "general", min_interval: float = 1800.0) -> None:
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


async def _morning_brief() -> None:
    try:
        from src.notifications.morning_brief import build_morning_brief
        brief_text = await asyncio.to_thread(build_morning_brief)
        await send_notification(brief_text, "brief", min_interval=3600)
    except Exception as e:
        logger.error("Morning brief failed: %s", e)


async def _coupon_check() -> None:
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
                await send_notification(text, nt, min_interval=86400)
        for ev in cal.redemptions:
            if ev.days_until in (7, 3, 1, 0):
                text = format_redemption_alert(ev, ev.days_until)
                await send_notification(text, "redemption", min_interval=86400)
    except Exception as e:
        logger.error("Coupon/redemption check failed: %s", e)


async def _rating_check() -> None:
    try:
        from src.notifications.rating_checker import check_rating_changes, format_rating_alert
        changes = await asyncio.to_thread(check_rating_changes)
        for change in changes:
            text = format_rating_alert(change)
            await send_notification(text, "rating", min_interval=86400)
    except Exception as e:
        logger.error("Rating check failed: %s", e)


async def _drawdown_check() -> None:
    try:
        from src.notifications.drawdown_checker import check_drawdown, format_drawdown_alert
        alert = await asyncio.to_thread(check_drawdown)
        if alert:
            text = format_drawdown_alert(alert)
            await send_notification(text, "drawdown", min_interval=3600)
    except Exception as e:
        logger.error("Drawdown check failed: %s", e)


async def _benchmark_comparison() -> None:
    try:
        from src.notifications.benchmark_comparison import compare_benchmarks, format_benchmark_comparison
        cmp = await asyncio.to_thread(compare_benchmarks)
        if cmp:
            text = format_benchmark_comparison(cmp)
            await send_notification(text, "benchmark", min_interval=86400)
    except Exception as e:
        logger.error("Benchmark comparison failed: %s", e)


async def _purchase_plan() -> None:
    try:
        from src.notifications.purchase_planner import format_purchase_plan, generate_purchase_plan
        plan = await asyncio.to_thread(generate_purchase_plan)
        if plan:
            text = format_purchase_plan(plan)
            await send_notification(text, "purchase_plan", min_interval=86400)
    except Exception as e:
        logger.error("Purchase plan failed: %s", e)


async def _tax_report() -> None:
    try:
        from src.notifications.tax_report import format_tax_report, generate_tax_report
        tax_report = await asyncio.to_thread(generate_tax_report)
        if tax_report:
            text = format_tax_report(tax_report)
            await send_notification(text, "tax", min_interval=86400)
    except Exception as e:
        logger.error("Tax report failed: %s", e)


async def _daily_snapshot() -> None:
    try:
        from src.scheduler.reporting import generate_daily_report, take_snapshot
        await take_snapshot("daily")
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
        from src.interfaces.telegram_broadcaster import (
            broadcast_author_posts,
            broadcast_dividends,
            broadcast_enrichment_alerts,
            broadcast_today_signals,
        )
        await broadcast_today_signals()
        await broadcast_dividends()
        await broadcast_enrichment_alerts()
        await broadcast_author_posts()
    except Exception as e:
        logger.error("Daily snapshot/report/broadcast failed: %s", e)


async def _weekly_snapshot() -> None:
    try:
        from src.scheduler.reporting import take_snapshot
        await take_snapshot("weekly")
    except Exception as e:
        logger.error("Weekly snapshot failed: %s", e)


async def _monthly_snapshot() -> None:
    try:
        from src.scheduler.reporting import take_snapshot
        await take_snapshot("monthly")
    except Exception as e:
        logger.error("Monthly snapshot failed: %s", e)


async def _weekly_update() -> None:
    try:
        await weekly_update()
    except Exception as e:
        logger.error("Weekly data update failed: %s", e)


async def _smart_rules() -> None:
    try:
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
            logger.exception("smart_rules_check_failed")
        finally:
            db.close()
    except Exception as e:
        logger.error("Smart rules check failed: %s", e)


async def _retry_receipts() -> None:
    try:
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
            logger.exception("retry_failed_receipts_crashed")
        finally:
            db.close()
    except Exception as e:
        logger.error("Retry receipts failed: %s", e)
