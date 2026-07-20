import logging

import typer
from rich.table import Table

from src.cli.output import console
from src.db.connection import get_session
from src.db.models import Instrument, Portfolio

from . import app, paper_app

logger = logging.getLogger(__name__)


@paper_app.command()
def buy(
    ticker: str = typer.Argument(..., help="Тикер"),
    quantity: float = typer.Argument(..., help="Количество"),
    price: float = typer.Argument(None, help="Цена (опционально)"),
    reason: str = typer.Option("", "--reason", "-r", help="Причина сделки"),
) -> None:
    """Купить тикер в paper-портфеле"""
    from src.trading.paper import PaperTradingEngine

    engine = PaperTradingEngine(user_id=0)
    result = engine.execute_order(ticker=ticker, direction="BUY", quantity=quantity, price=price, reason=reason)
    if result["status"] == "error":
        console.print(f"[red]Ошибка:[/red] {result['error']}")
    else:
        console.print(f"[green]Куплено[/green] {result['quantity']:.0f} {ticker} @ {result['price']:.2f}")
        console.print(f"  Комиссия: {result['commission']:.2f} ₽")
        console.print(f"  Баланс после: {result['balance_after']:,.2f} ₽")
        console.print(f"  Total equity: {result['total_equity']:,.2f} ₽")


@paper_app.command()
def sell(
    ticker: str = typer.Argument(..., help="Тикер"),
    quantity: float = typer.Argument(None, help="Количество (все, если не указано)"),
    price: float = typer.Argument(None, help="Цена (опционально)"),
    reason: str = typer.Option("", "--reason", "-r", help="Причина сделки"),
) -> None:
    """Продать тикер из paper-портфеля"""
    from src.trading.paper import PaperTradingEngine

    engine = PaperTradingEngine(user_id=0)
    if quantity is None:
        pos = engine.get_positions().get(ticker.upper())
        if not pos:
            console.print(f"[red]Нет позиции {ticker}[/red]")
            return
        quantity = pos.quantity
    result = engine.execute_order(ticker=ticker, direction="SELL", quantity=quantity, price=price, reason=reason)
    if result["status"] == "error":
        console.print(f"[red]Ошибка:[/red] {result['error']}")
    else:
        console.print(f"[yellow]Продано[/yellow] {result['quantity']:.0f} {ticker} @ {result['price']:.2f}")
        console.print(f"  P&L: {result['pnl']:+,.2f} ₽")
        console.print(f"  Комиссия: {result['commission']:.2f} ₽")
        console.print(f"  Баланс после: {result['balance_after']:,.2f} ₽")


@paper_app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-l", help="Количество записей"),
) -> None:
    """Показать историю paper-сделок"""
    from src.trading.paper import PaperTradingEngine

    engine = PaperTradingEngine(user_id=0)
    trades = engine.get_trades(limit=limit)
    if not trades:
        console.print("[dim]Нет сделок[/dim]")
        return
    table = Table(title=f"Paper trades (last {len(trades)})")
    table.add_column("Время", style="dim")
    table.add_column("Тикер", style="cyan")
    table.add_column("Напр.", style="yellow")
    table.add_column("Кол-во", justify="right")
    table.add_column("Цена", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("Баланс", justify="right")
    table.add_column("Причина")
    for t in reversed(trades):
        pnl_str = f"{t['pnl']:+,.2f}" if t["pnl"] else "-"
        table.add_row(
            t["timestamp"][:19],
            t["ticker"],
            t["direction"],
            f"{t['quantity']:.0f}",
            f"{t['price']:.2f}",
            pnl_str,
            f"{t['balance_after']:,.0f}",
            t["reason"],
        )
    console.print(table)


@app.command()
def seed_portfolio(
    reset: bool = typer.Option(False, "--reset", help="Сбросить и пересоздать"),
) -> None:
    """Создать тестовый портфель (SBER, GAZP, LKOH)"""
    db = get_session()
    try:
        if reset:
            db.query(Portfolio).delete()
            db.commit()
        existing = db.query(Portfolio).count()
        if existing > 0:
            console.print(f"[yellow]Портфель уже содержит {existing} позиций[/yellow]")
            return

        data = [("SBER", 100, 287.50), ("GAZP", 50, 165.30), ("LKOH", 10, 7100.00)]
        for ticker, qty, price in data:
            inst = db.query(Instrument).filter_by(ticker=ticker).first()
            if not inst:
                console.print(f"[red]Инструмент {ticker} не найден[/red]")
                continue
            db.add(Portfolio(instrument_id=inst.id, quantity=qty, avg_price=price))
        db.commit()
        console.print("[green]Тестовый портфель создан:[/green]")
        for ticker, qty, price in data:
            console.print(f"  {ticker}: {qty} шт. × {price} ₽")
    finally:
        db.close()


@app.command()
def prune_models(max_versions: int = 5) -> None:
    """Удалить устаревшие версии ML-моделей (оставить только max_versions последних)"""
    from src.model_registry import prune_models as _prune

    result = _prune(max_versions=max_versions)
    console.print(f"[green]✓[/green] Pruned: {result['registry_pruned']} versions, {result['orphan_files_removed']} orphans")
