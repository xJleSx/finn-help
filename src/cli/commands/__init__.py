from __future__ import annotations

import logging
import sys
from typing import Optional

import typer

from src.cli.output import console as console
from src.social.cli import social_app

if sys.stdout.encoding != "utf-8" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = typer.Typer(
    help="FinAdvisor — AI финансовый ассистент для MOEX",
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
logger = logging.getLogger(__name__)
paper_app = typer.Typer(help="Paper trading — симуляция сделок без реальных денег")

from .analysis import analyze as analyze  # noqa: E402
from .analysis import auto as auto  # noqa: E402
from .analysis import full_cycle as full_cycle  # noqa: E402
from .analysis import metrics as metrics  # noqa: E402
from .analysis import run_analysis as run_analysis  # noqa: E402
from .analysis import status as status  # noqa: E402
from .analysis import train_models as train_models  # noqa: E402
from .data import _update_ticker as _update_ticker  # noqa: E402
from .data import bond as bond  # noqa: E402
from .data import discover_bonds as discover_bonds  # noqa: E402
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

security_app = typer.Typer(help="Security utilities — encryption, key generation, checks")
app.add_typer(security_app, name="security")
from .security import (  # noqa: E402
    check_env as check_env,
)
from .security import (
    encrypt_value as encrypt_value,
)
from .security import (
    generate_jwt_refresh_secret as generate_jwt_refresh_secret,
)
from .security import (
    generate_jwt_secret as generate_jwt_secret,
)
from .security import (
    generate_key as generate_key,
)
from .trading import buy as buy  # noqa: E402
from .trading import history as history  # noqa: E402
from .trading import prune_models as prune_models  # noqa: E402
from .trading import seed_portfolio as seed_portfolio  # noqa: E402
from .trading import sell as sell  # noqa: E402

app.add_typer(paper_app, name="paper")
app.add_typer(social_app, name="social")

from src.cli.output import set_output_format
from src.cli.tui import run_dashboard  # noqa: E402


@app.command(name="dashboard")
def dashboard(
    refresh: int = typer.Option(5, "--refresh", "-r", help="Refresh interval in seconds"),
) -> None:
    """Запустить TUI дашборд."""
    run_dashboard(refresh_interval=refresh)


@app.callback()
def main_callback(
    ctx: typer.Context,
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: text or json",
        case_sensitive=False,
    ),
) -> None:
    if output:
        set_output_format(output)


def main() -> None:
    app()
