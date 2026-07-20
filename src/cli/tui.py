from __future__ import annotations

from datetime import date, datetime

from rich import box
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.cli.output import console
from src.db.connection import get_session
from src.db.models import Instrument, Price, Signal


def _build_portfolio_table() -> Table:
    table = Table(box=box.SIMPLE, title="Portfolio Overview", title_style="bold green")
    table.add_column("Ticker", style="cyan")
    table.add_column("Price", justify="right")
    table.add_column("Change %", justify="right")
    table.add_column("Signal", style="yellow")
    table.add_column("Confidence", justify="right")
    db = get_session()
    try:
        today = date.today()
        signals = (
            db.query(Signal)
            .filter(Signal.date >= today)
            .order_by(Signal.confidence.desc())
            .limit(10)
            .all()
        )
        for sig in signals:
            inst = db.query(Instrument).filter_by(id=sig.instrument_id).first()
            ticker = inst.ticker if inst else "?"
            last_price = (
                db.query(Price)
                .filter_by(instrument_id=sig.instrument_id)
                .order_by(Price.date.desc())
                .first()
            )
            price_str = f"{last_price.close:.2f}" if last_price and last_price.close else "N/A"
            change = ""
            if last_price and last_price.close:
                prev = (
                    db.query(Price)
                    .filter_by(instrument_id=sig.instrument_id)
                    .order_by(Price.date.desc())
                    .offset(1)
                    .first()
                )
                if prev and prev.close:
                    pct = (last_price.close - prev.close) / prev.close * 100
                    color = "green" if pct >= 0 else "red"
                    change = f"[{color}]{pct:+.2f}%[/{color}]"
            table.add_row(
                ticker,
                price_str,
                change or "N/A",
                str(sig.action or "HOLD"),
                f"{sig.confidence:.0%}" if sig.confidence else "N/A",
            )
    finally:
        db.close()
    return table


def _build_status_panel() -> Panel:
    db = get_session()
    try:
        total_instruments = db.query(Instrument).count()
        today = date.today()
        today_signals = db.query(Signal).filter(Signal.date >= today).count()
        last_price = (
            db.query(Price)
            .join(Instrument)
            .filter(Instrument.ticker == "IMOEX")
            .order_by(Price.date.desc())
            .first()
        )
        imoex = f"{last_price.close:.0f}" if last_price and last_price.close else "N/A"
    finally:
        db.close()
    content = (
        f"Instruments: {total_instruments}\n"
        f"Signals today: {today_signals}\n"
        f"IMOEX: {imoex}\n"
        f"Updated: {datetime.now():%H:%M:%S}"
    )
    return Panel(content, title="[bold cyan]FinAdvisor Status[/]", box=box.ROUNDED)


def _build_header() -> Panel:
    text = Text("FinAdvisor — AI Financial Assistant for MOEX", style="bold white on blue")
    text.stylize("bold white on blue")
    return Panel(text, box=box.HEAVY)


def build_dashboard() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(_build_header(), size=3),
        Layout(
            name="main",
            ratio=1,
        ),
    )
    layout["main"].split_row(
        Layout(_build_portfolio_table(), name="portfolio", ratio=2),
        Layout(_build_status_panel(), name="status", ratio=1),
    )
    return layout


def run_dashboard(refresh_interval: int = 5) -> None:
    with Live(build_dashboard(), refresh_per_second=1 / refresh_interval, screen=True) as live:
        import time

        try:
            while True:
                live.update(build_dashboard())
                time.sleep(refresh_interval)
        except KeyboardInterrupt:
            console.print("\n[yellow]Dashboard closed.[/yellow]")
