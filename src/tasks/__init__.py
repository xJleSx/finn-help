from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from src.config import settings

app = Celery(
    "finn_advisor",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.celery_task_always_eager,
    worker_concurrency=settings.celery_worker_concurrency,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_hard_time_limit=settings.celery_task_hard_time_limit,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
    beat_max_loop_interval=60,
)

import re

_NAME_RE = re.compile(r"^[a-z0-9_-]+$")

for _name in list(app.conf.beat_schedule.keys()):
    if not _NAME_RE.match(_name):
        import warnings
        warnings.warn(f"Beat schedule task name '{_name}' does not match pattern a-z0-9_-")

app.conf.beat_schedule = {
    "recurring-update-every-5min": {
        "task": "run_daily_update",
        "schedule": 300,
        "args": (),
    },
    "smart-rules-every-30min": {
        "task": "check_smart_rules",
        "schedule": 1800,
        "args": (),
    },
    "retry-receipts-every-30min": {
        "task": "retry_failed_receipts",
        "schedule": 1800,
        "args": (),
    },
    "collect-prices-every-6h": {
        "task": "collect_prices",
        "schedule": 21600,
        "args": (),
    },
    "generate-signals-every-4h": {
        "task": "generate_signals_background",
        "schedule": 14400,
        "args": (None,),
    },
    "train-models-daily": {
        "task": "train_all_models",
        "schedule": 86400,
        "args": (),
    },
    "daily-snapshot-at-2350-msk": {
        "task": "take_daily_snapshot",
        "schedule": crontab(hour=20, minute=50),
        "args": (),
    },
    "weekly-update-on-friday": {
        "task": "run_weekly_update",
        "schedule": crontab(hour=19, minute=0, day_of_week=4),
        "args": (),
    },
    "weekly-snapshot-on-friday": {
        "task": "take_weekly_snapshot",
        "schedule": crontab(hour=20, minute=0, day_of_week=4),
        "args": (),
    },
    "monthly-snapshot-on-1st": {
        "task": "take_monthly_snapshot",
        "schedule": crontab(hour=19, minute=0, day_of_month=1),
        "args": (),
    },
    "clear-stale-cache-daily": {
        "task": "clear_stale_feature_cache",
        "schedule": crontab(hour=0, minute=0),
        "args": (),
    },
    "daily-report-at-2350-msk": {
        "task": "run_daily_report",
        "schedule": crontab(hour=20, minute=55),
        "args": (),
    },
    "weekly-report-on-friday": {
        "task": "run_weekly_report",
        "schedule": crontab(hour=20, minute=30, day_of_week=4),
        "args": (),
    },
    "monthly-report-on-1st": {
        "task": "run_monthly_report",
        "schedule": crontab(hour=20, minute=30, day_of_month=1),
        "args": (),
    },
}

app.autodiscover_tasks(["src.tasks"])

app.conf.task_routes = {
    "run_daily_update": {"queue": "default"},
    "run_weekly_update": {"queue": "default"},
    "generate_signals_background": {"queue": "ml"},
    "train_model": {"queue": "ml"},
    "train_all_models": {"queue": "ml"},
    "collect_prices": {"queue": "data"},
}

if app.conf.task_always_eager and not settings.log_level == "DEBUG":
    import warnings
    warnings.warn("task_always_eager=True in non-DEBUG mode — tasks run synchronously in the main process")
