from __future__ import annotations

import logging
from typing import Any

from src.tasks import app

logger = logging.getLogger(__name__)


from src.tasks._utils import run_async as _run_async


@app.task(bind=True, max_retries=2, name="run_daily_update")
def run_daily_update(self) -> dict[str, Any]:
    """Execute the daily update cycle (prices, news, signals) in background."""
    from src.scheduler.tasks import daily_update

    logger.info("Running daily update via Celery task")
    try:
        _run_async(daily_update())
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Daily update failed")
        try:
            self.retry(exc=e)
        except Exception:
            logger.exception("Unhandled exception")
            return {"status": "error", "error": str(e)}


@app.task(bind=True, max_retries=2, name="run_weekly_update")
def run_weekly_update(self) -> dict[str, Any]:
    """Execute the weekly update cycle (reports, rebalance) in background."""
    from src.scheduler.tasks import weekly_update

    logger.info("Running weekly update via Celery task")
    try:
        _run_async(weekly_update())
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Weekly update failed")
        try:
            self.retry(exc=e)
        except Exception:
            logger.exception("Unhandled exception")
            return {"status": "error", "error": str(e)}


@app.task(bind=True, name="run_daily_report")
def run_daily_report(self) -> dict[str, Any]:
    """Generate and broadcast daily report."""
    from src.scheduler.reporting import generate_and_send_daily_report

    try:
        generate_and_send_daily_report()
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Daily report failed")
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="run_weekly_report")
def run_weekly_report(self) -> dict[str, Any]:
    """Generate and broadcast weekly report."""
    from src.scheduler.reporting import generate_and_send_weekly_report

    try:
        generate_and_send_weekly_report()
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Weekly report failed")
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="run_monthly_report")
def run_monthly_report(self) -> dict[str, Any]:
    """Generate and broadcast monthly report."""
    from src.scheduler.reporting import generate_and_send_monthly_report

    try:
        generate_and_send_monthly_report()
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Monthly report failed")
        return {"status": "error", "error": str(e)}


def _snapshot_data() -> None:
    from src.scheduler.reporting import take_snapshot
    _run_async(take_snapshot("daily"))


def _generate_and_send_report() -> None:
    from src.scheduler.reporting import generate_daily_report
    report = _run_async(generate_daily_report())
    if not report or not report.report_text:
        return
    from src.interfaces.telegram import app as bot_app
    if bot_app is not None:
        from src.notifications.service import NotificationService
        ns = NotificationService()
        for uid, cid in ns.get_subscribers("daily"):
            chat_id = cid
            if not chat_id:
                from src.db.connection import get_session
                from src.db.models import Subscription
                _db = get_session()
                try:
                    sub = _db.query(Subscription).filter_by(user_id=uid).first()
                    chat_id = sub.chat_id if sub else None
                finally:
                    _db.close()
            if not chat_id:
                logger.warning("No chat_id for user %d, skipping daily report", uid)
                continue
            try:
                _run_async(bot_app.bot.send_message(chat_id=chat_id, text=report.report_text, parse_mode="HTML"))
            except Exception as e:
                logger.warning("Failed to send daily report to %d: %s", chat_id, e)
    else:
        logger.info("Daily report:\n%s", report.report_text)


def _broadcast_today_signals() -> None:
    from src.interfaces.telegram_broadcaster import broadcast_today_signals
    _run_async(broadcast_today_signals())


def _broadcast_dividends() -> None:
    from src.interfaces.telegram_broadcaster import broadcast_dividends
    _run_async(broadcast_dividends())


def _broadcast_enrichment_alerts() -> None:
    from src.interfaces.telegram_broadcaster import broadcast_enrichment_alerts
    _run_async(broadcast_enrichment_alerts())


def _broadcast_author_posts() -> None:
    from src.interfaces.telegram_broadcaster import broadcast_author_posts
    _run_async(broadcast_author_posts())


@app.task(bind=True, name="take_daily_snapshot")
def take_daily_snapshot(self) -> dict[str, Any]:
    logger.info("Taking daily snapshot via Celery task")
    try:
        _snapshot_data()
        _generate_and_send_report()
        _broadcast_today_signals()
        _broadcast_dividends()
        _broadcast_enrichment_alerts()
        _broadcast_author_posts()
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Daily snapshot failed")
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="take_weekly_snapshot")
def take_weekly_snapshot(self) -> dict[str, Any]:
    from src.scheduler.reporting import take_snapshot

    logger.info("Taking weekly snapshot via Celery task")
    try:
        _run_async(take_snapshot("weekly"))
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Weekly snapshot failed")
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="take_monthly_snapshot")
def take_monthly_snapshot(self) -> dict[str, Any]:
    from src.scheduler.reporting import take_snapshot

    logger.info("Taking monthly snapshot via Celery task")
    try:
        _run_async(take_snapshot("monthly"))
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Monthly snapshot failed")
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="check_smart_rules")
def check_smart_rules(self) -> dict[str, Any]:
    from src.alerts.history import AlertHistory
    from src.alerts.smart import SmartAlertEngine
    from src.db.connection import get_session

    db = get_session()
    try:
        engine = SmartAlertEngine()
        triggered = engine.evaluate_rules(db)
        if triggered:
            history = AlertHistory(db=db)
            for alert in triggered:
                history.log_alert(alert)
            logger.info("Smart rules triggered %d alerts", len(triggered))
        return {"status": "ok", "triggered": len(triggered)}
    except Exception as e:
        logger.exception("Smart rules check failed")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@app.task(bind=True, name="retry_failed_receipts")
def retry_failed_receipts(self) -> dict[str, Any]:
    from src.db.connection import get_session
    from src.notifications.retry import ReceiptManager

    db = get_session()
    try:
        mgr = ReceiptManager(db)
        pending = mgr.get_pending_retries(limit=20)
        if not pending:
            return {"status": "ok", "retried": 0}
        count = 0
        for receipt in pending:
            try:
                from src.notifications.channels import PushMessage
                msg = PushMessage(
                    title=receipt.title or "",
                    body=receipt.message or "",
                    ticker="",
                    priority=0,
                    alert_type=receipt.notification_type or "general",
                )
                if receipt.channel == "email":
                    from src.notifications.channels import EmailPushChannel
                    channel = EmailPushChannel(db=db)
                    success = channel.send("", msg)
                elif receipt.channel == "telegram":
                    from src.interfaces.telegram import app as bot_app
                    success = False
                    if bot_app is not None:
                        try:
                            import asyncio
                            asyncio.run(bot_app.bot.send_message(
                                chat_id=receipt.user_id,
                                text=receipt.message or "",
                            ))
                            success = True
                        except Exception:
                            success = False
                elif receipt.channel == "web":
                    from src.notifications.channels import WebPushChannel
                    web = WebPushChannel()
                    success = web.send(receipt.user_id, msg)
                else:
                    success = False
                if success:
                    mgr.mark_sent(receipt.id)
                else:
                    mgr.mark_failed(receipt.id, "send returned False")
                count += 1
            except Exception as exc:
                logger.exception("receipt_retry_failed", receipt_id=receipt.id)
                mgr.mark_failed(receipt.id, str(exc)[:500], schedule_retry=True)
        return {"status": "ok", "retried": count}
    except Exception as e:
        logger.exception("Receipt retry failed")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@app.task(name="clear_stale_feature_cache")
def clear_stale_feature_cache() -> dict[str, Any]:
    from src.analysis.feature_store import clear_stale

    count = clear_stale(max_age_days=7)
    logger.info("Cleared %d stale feature cache entries", count)
    return {"status": "ok", "cleared": count}
