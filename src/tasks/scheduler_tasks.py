from __future__ import annotations

import logging
from typing import Any

from src.tasks import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=2, name="run_daily_update")
def run_daily_update(self) -> dict[str, Any]:
    """Execute the daily update cycle (prices, news, signals) in background."""
    from src.scheduler.tasks import daily_update

    logger.info("Running daily update via Celery task")
    try:
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(daily_update())
            return {"status": "ok"}
        finally:
            loop.close()
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
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(weekly_update())
            return {"status": "ok"}
        finally:
            loop.close()
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
