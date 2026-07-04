from __future__ import annotations

from celery import Celery

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
)

app.conf.beat_schedule = {
    "collect-prices-every-6h": {
        "task": "collect_prices",
        "schedule": 21600,
        "args": (),
    },
    "train-models-daily": {
        "task": "train_all_models",
        "schedule": 86400,
        "args": (),
    },
    "generate-signals-every-4h": {
        "task": "generate_signals_background",
        "schedule": 14400,
        "args": (None,),
    },
}

app.autodiscover_tasks(["src.tasks"])
