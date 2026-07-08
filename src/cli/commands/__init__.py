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

# Import command modules after app creation to resolve circular deps (noqa: E402)
from .analysis import analyze as analyze  # noqa: E402
from .analysis import auto as auto  # noqa: E402
from .analysis import full_cycle as full_cycle  # noqa: E402
from .analysis import metrics as metrics  # noqa: E402
from .analysis import run_analysis as run_analysis  # noqa: E402
from .analysis import status as status  # noqa: E402
from .analysis import train_models as train_models  # noqa: E402
from .data import _update_ticker as _update_ticker  # noqa: E402
from .data import bond as bond  # noqa: E402
from .data import financials as financials  # noqa: E402
from .data import list_instruments as list_instruments  # noqa: E402
from .data import macro as macro  # noqa: E402
from .data import rates as rates  # noqa: E402
from .data import scan as scan  # noqa: E402
from .data import sectors as sectors  # noqa: E402
from .data import update as update  # noqa: E402
from .misc import bot as bot  # noqa: E402
from .misc import callback as callback  # noqa: E402
from .misc import init as init  # noqa: E402
from .misc import reset as reset  # noqa: E402
from .misc import scheduler as scheduler  # noqa: E402
from .trading import buy as buy  # noqa: E402
from .trading import history as history  # noqa: E402
from .trading import prune_models as prune_models  # noqa: E402
from .trading import seed_portfolio as seed_portfolio  # noqa: E402
from .trading import sell as sell  # noqa: E402

app.add_typer(paper_app, name="paper")
app.add_typer(social_app, name="social")


def main() -> None:
    app()
