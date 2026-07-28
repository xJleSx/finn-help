import os
import tempfile
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.scheduler.notifications import (
    _benchmark_comparison,
    _coupon_check,
    _daily_snapshot,
    _drawdown_check,
    _monthly_snapshot,
    _morning_brief,
    _purchase_plan,
    _rating_check,
    _retry_receipts,
    _smart_rules,
    _tax_report,
    _weekly_snapshot,
    _weekly_update,
)
from src.scheduler.tasks import (
    clear_stale_feature_cache_background,
    collect_prices_background,
    generate_signals_background,
    train_models_background,
)

logger = structlog.get_logger(__name__)

scheduler: AsyncIOScheduler | None = None


def _acquire_instance_lock(name: str = "scheduler") -> bool:
    lock_dir = Path(os.environ.get("FINN_LOCK_DIR", tempfile.gettempdir()))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"finn_{name}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
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


def start() -> AsyncIOScheduler:
    global scheduler, _INSTANCE_LOCK_HELD
    if not _acquire_instance_lock("scheduler"):
        logger.error("Another scheduler instance is already running")
        raise RuntimeError("Scheduler lock already held")
    _INSTANCE_LOCK_HELD = True

    sched = AsyncIOScheduler(timezone="Europe/Moscow")

    # Daily update (every 5 min during market hours, simplified to every 4h)
    sched.add_job(daily_update_wrapper, CronTrigger(hour="*/4", minute="5"), id="daily_update", replace_existing=True)

    # Price collection every 6h
    sched.add_job(collect_prices_background, CronTrigger(hour="3,9,15,21", minute="0"), id="collect_prices", replace_existing=True)

    # Signal generation every 4h
    sched.add_job(generate_signals_background, CronTrigger(hour="2,6,10,14,18,22", minute="0"), id="generate_signals", replace_existing=True)

    # ML model training daily at 1:00
    sched.add_job(train_models_background, CronTrigger(hour="1", minute="0"), id="train_models", replace_existing=True)

    # Stale cache cleanup daily at 0:00
    sched.add_job(clear_stale_feature_cache_background, CronTrigger(hour="0", minute="0"), id="clear_cache", replace_existing=True)

    # ── Notifications ─────────────────────────────────────────────

    # Daily snapshot at 23:50
    sched.add_job(_daily_snapshot, CronTrigger(hour="23", minute="50"), id="daily_snapshot", replace_existing=True)

    # Morning brief at 9:00
    sched.add_job(_morning_brief, CronTrigger(hour="9", minute="0"), id="morning_brief", replace_existing=True)

    # Coupon/redemption check at 10:00
    sched.add_job(_coupon_check, CronTrigger(hour="10", minute="0"), id="coupon_check", replace_existing=True)

    # Rating check at 11:00
    sched.add_job(_rating_check, CronTrigger(hour="11", minute="0"), id="rating_check", replace_existing=True)

    # Drawdown check every 15 min
    sched.add_job(_drawdown_check, CronTrigger(minute="*/15"), id="drawdown_check", replace_existing=True)

    # Weekly: snapshot + update, Friday 23:50
    sched.add_job(_weekly_snapshot, CronTrigger(day_of_week="fri", hour="23", minute="50"), id="weekly_snapshot", replace_existing=True)
    sched.add_job(_weekly_update, CronTrigger(day_of_week="fri", hour="23", minute="55"), id="weekly_update", replace_existing=True)

    # Monthly snapshot, 1st day 23:55
    sched.add_job(_monthly_snapshot, CronTrigger(day="1", hour="23", minute="55"), id="monthly_snapshot", replace_existing=True)

    # Benchmark comparison, Friday 12:00
    sched.add_job(_benchmark_comparison, CronTrigger(day_of_week="fri", hour="12", minute="0"), id="benchmark", replace_existing=True)

    # Purchase planner, 23-24th at 10:00
    sched.add_job(_purchase_plan, CronTrigger(day="23,24", hour="10", minute="0"), id="purchase_plan", replace_existing=True)

    # Tax report, 1st of month at 10:00
    sched.add_job(_tax_report, CronTrigger(day="1", hour="10", minute="0"), id="tax_report", replace_existing=True)

    # Smart rules every 30 min
    sched.add_job(_smart_rules, CronTrigger(minute="*/30"), id="smart_rules", replace_existing=True)

    # Retry receipts every 60 min
    sched.add_job(_retry_receipts, CronTrigger(hour="*"), id="retry_receipts", replace_existing=True)

    sched.start()
    scheduler = sched
    logger.info("APScheduler started with %d jobs", len(sched.get_jobs()))
    return sched


async def daily_update_wrapper() -> None:
    from src.scheduler.tasks import daily_update
    try:
        await daily_update()
    except Exception as e:
        logger.error("Daily update failed: %s", e)


def is_running() -> bool:
    return scheduler is not None and scheduler.running


def stop() -> None:
    global scheduler, _INSTANCE_LOCK_HELD
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
        logger.info("Scheduler stopped")
    if _INSTANCE_LOCK_HELD:
        _release_instance_lock("scheduler")
        _INSTANCE_LOCK_HELD = False


async def start_background() -> None:
    start()
