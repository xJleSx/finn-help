import asyncio
import logging

import typer

from src.cli.output import console
from src.db.connection import init_db

from . import app, paper_app  # noqa: PLC0415 — app/paper_app defined in __init__ before submodule imports

logger = logging.getLogger(__name__)


@app.callback()
def callback() -> None:
    pass


@app.command()
def init() -> None:
    """Инициализировать базу данных"""
    init_db()
    console.print("[green]OK[/green] База данных инициализирована")


@app.command()
def bot() -> None:
    """Запустить Telegram бота"""
    from src.interfaces.telegram import run_bot

    asyncio.run(run_bot())


@app.command()
def scheduler() -> None:
    """Запустить фоновый scheduler (обновление каждый час)"""
    from src.scheduler.service import run_forever

    asyncio.run(run_forever())


@app.command()
def celery_worker() -> None:
    """Запустить Celery worker для фоновых задач"""
    from src.tasks import app as celery_app

    celery_app.start(argv=["celery", "worker", "-A", "src.tasks", "-l", "INFO"])


@app.command()
def celery_beat() -> None:
    """Запустить Celery beat для расписания задач"""
    from src.tasks import app as celery_app

    celery_app.start(argv=["celery", "beat", "-A", "src.tasks", "-l", "INFO", "--scheduler", "celery.beat.PersistentScheduler"])


@paper_app.command()
def reset(
    capital: float = typer.Option(1_000_000, "--capital", "-c", help="Начальный капитал"),
) -> None:
    """Сбросить paper-счёт"""
    from src.trading.paper import PaperTradingEngine

    engine = PaperTradingEngine(user_id=0)
    state = engine.reset(initial_capital=capital)
    console.print(f"[green]Paper-счёт сброшен.[/green] Баланс: {state.balance:,.2f} ₽")
