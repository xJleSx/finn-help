"""Entry point for the Celery worker process.

Usage:
    uv run python -m src.tasks.worker
    uv run celery -A src.tasks worker -l INFO
    uv run celery -A src.tasks beat -l INFO
"""

from src.tasks import app

if __name__ == "__main__":
    import os
    concurrency = os.environ.get("CELERY_WORKER_CONCURRENCY", "2")
    app.start(argv=["celery", "worker", "-A", "src.tasks", "-l", "INFO", f"--concurrency={concurrency}"])
