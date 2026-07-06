import logging
import sys

import typer
from rich.console import Console

from src.social.cli import social_app

if sys.stdout.encoding != "utf-8" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

console = Console()
app = typer.Typer(help="FinAdvisor — AI финансовый ассистент для MOEX")
logger = logging.getLogger(__name__)
paper_app = typer.Typer(help="Paper trading — симуляция сделок без реальных денег")

from .data import _update_ticker, update, list_instruments, rates, macro, sectors, financials, bond, scan
from .analysis import run_analysis, analyze, auto, full_cycle, metrics, status, train_models
from .trading import buy, sell, history, seed_portfolio, prune_models
from .misc import init, callback, bot, scheduler, reset

app.add_typer(paper_app, name="paper")
app.add_typer(social_app, name="social")


def main() -> None:
    app()
