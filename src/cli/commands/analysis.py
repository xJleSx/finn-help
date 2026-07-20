import asyncio
import logging
from typing import Any, Optional

import pandas as pd
import typer
from rich.progress import Progress
from rich.table import Table

from src.analysis.personal_backtest import run_personal_backtest
from src.analysis.service import analysis_service
from src.cli.output import console
from src.collectors.cbr import CBRCollector
from src.collectors.moex import MOEXCollector
from src.config import personal
from sqlalchemy import select

from src.db.connection import get_async_session
from src.db.models import Instrument, Price
from src.llm.router import llm

from . import app, paper_app

logger = logging.getLogger(__name__)


async def run_analysis(ticker: str, with_llm: bool = True, with_ml: bool = True) -> tuple[dict[str, Any] | None, str]:
    async with get_async_session() as db:
        result = await db.execute(select(Instrument).filter_by(ticker=ticker.upper()))
        inst = result.scalars().first()
        if not inst:
            return None, f"Инструмент {ticker} не найден"
        fused = analysis_service._analyze_single_sync(db, inst, ticker.upper(), with_ml=with_ml)
        if with_llm:
            advice = await llm.advise(fused)
        else:
            advice = ""
        return fused, advice


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="Тикер (например, SBER)"),
    with_llm: bool = typer.Option(True, "--llm/--no-llm", help="Использовать LLM для совета"),
    report: bool = typer.Option(False, "--report", "-r", help="Формат инвестиционного обзора"),
) -> None:
    """Проанализировать инструмент"""

    async def _run() -> None:
        async with get_async_session() as db:
            result = await db.execute(select(Instrument).filter_by(ticker=ticker.upper()))
            inst = result.scalars().first()
            if not inst:
                console.print(f"[red]✗[/red] Инструмент {ticker} не найден")
                return

            price_result = await db.execute(
                select(Price).filter_by(instrument_id=inst.id).order_by(Price.date)
            )
            prices_q = price_result.scalars().all()
            if not prices_q:
                console.print(f"[red]✗[/red] Нет данных для {ticker}")
                return

            with Progress(console=console) as p:
                p.add_task("Анализ...", total=None)
                fused: dict[str, Any] | None
                advice: str
                if report:
                    fused = analysis_service._analyze_single_sync(db, inst, ticker.upper())
                    from src.llm.router import llm

                    advice = await llm.report(fused)
                else:
                    fused, advice = await run_analysis(ticker, with_llm)

            if not fused:
                return

            if report:
                console.print(advice)
                return

            df = pd.DataFrame(
                [
                    {
                        "date": p.date,
                        "open": p.open,
                        "high": p.high,
                        "low": p.low,
                        "close": p.close,
                        "volume": p.volume,
                    }
                    for p in prices_q
                ]
            )
            df_ind = analysis_service.analyzer.compute_all(df)
            last = df_ind.iloc[-1] if not df_ind.empty else None

            table = Table(title=f"📊 {ticker.upper()} — анализ")
            table.add_column("Показатель", style="cyan")
            table.add_column("Значение", style="yellow")

            if last is not None:
                price = last.get("close", "—")
                table.add_row("Цена", f"{price:.2f} ₽" if isinstance(price, float) else str(price))
                for col in ["rsi", "macd_hist", "sma_20", "sma_50", "sma_200"]:
                    val = last.get(col)
                    if val is not None and not pd.isna(val):
                        table.add_row(col.upper(), f"{val:.2f}")
                for col in ["bb_upper", "bb_lower"]:
                    val = last.get(col)
                    if val is not None and not pd.isna(val):
                        table.add_row(col.upper(), f"{val:.2f}")
                table.add_row(
                    "Сигнал",
                    f"[bold]{fused.get('action', 'HOLD')}[/bold] (уверенность: {fused.get('confidence', 0):.0%})",
                )
                table.add_row("Макс. доля", f"до {fused.get('max_portfolio_pct', 10)}% портфеля")

            console.print(table)

            if advice:
                console.print(f"\n[bold]🤖 Совет:[/bold]\n{advice}")

    asyncio.run(_run())


@app.command()
def auto() -> None:
    """Запустить полный цикл: обновить ВСЕ MOEX + анализ + сигналы"""

    async def _run() -> None:
        from src.scheduler.tasks import daily_update

        console.print("[bold]🚀 Запуск автономного цикла...[/bold]")
        await daily_update()
        console.print("[green]✓[/green] Цикл завершён. Все инструменты проанализированы.")

    asyncio.run(_run())


@app.command()
def full_cycle() -> None:
    """Полный цикл: update → train → backtest → report"""
    from datetime import datetime, timezone

    console.print("[bold]🚀 Запуск полного цикла[/bold]")
    start = datetime.now(timezone.utc)

    # 1. Update data
    console.print("\n[bold cyan]1/4 Обновление данных...[/bold cyan]")
    import asyncio

    async def _update() -> None:
        async with MOEXCollector() as moex:
            raw = personal.get("favorite_tickers", ["SBER", "LKOH", "GAZP", "YNDX", "TATN"])
            tickers = [str(t) for t in raw] if isinstance(raw, list) else ["SBER", "LKOH", "GAZP", "YNDX", "TATN"]
            for t in tickers:
                await moex.get_history(t)
                console.print(f"  ✓ {t}")
            await CBRCollector().get_rates()

    asyncio.run(_update())

    # 2. Train models
    console.print("\n[bold cyan]2/4 Обучение моделей...[/bold cyan]")
    try:
        db = get_session()
        try:
            results = analysis_service.train_models(db)
            success = sum(1 for v in results.values() if v)
            total = len(results)
            console.print(f"  ✓ Модели обучены: {success}/{total} инструментов")
        finally:
            db.close()
    except Exception as e:
        logger.warning("Train error: %s", e)
        console.print("  [yellow]⚠ Обучение пропущено[/yellow]")

    # 3. Personal backtest
    console.print("\n[bold cyan]3/4 Персональный бэктест...[/bold cyan]")
    result = run_personal_backtest()
    console.print(result.summary())

    # 4. Report
    console.print("\n[bold cyan]4/4 Результаты[/bold cyan]")
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    console.print(f"\n[green]✅ Цикл завершён за {elapsed:.0f}с[/green]")

    # equity curve to CSV
    csv_path = f"data/full_cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        ec = result.equity_curve
        if ec:
            import csv

            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["date", "portfolio", "benchmark"])
                w.writeheader()
                w.writerows(ec)
            console.print(f"  📄 Equity curve saved → {csv_path}")
    except Exception as e:
        logger.warning("Failed to save equity curve: %s", e)


@app.command()
def train_models(
    ticker: Optional[str] = typer.Argument(None, help="Тикер (например, SBER), все если не указан"),
) -> None:
    """Обучить и сохранить ML-модели для инструментов"""
    db = get_session()
    try:
        with console.status("Обучение моделей..."):
            results = analysis_service.train_models(db, ticker=ticker)
        success = sum(1 for v in results.values() if v)
        total = len(results)
        if total == 0:
            console.print("[yellow]Нет инструментов для обучения[/yellow]")
            return
        table = Table(title=f"🤖 Обучение моделей: {success}/{total} OK")
        table.add_column("Тикер", style="cyan")
        table.add_column("Результат", style="yellow")
        for t, ok in sorted(results.items()):
            table.add_row(t, "[green]✓[/green]" if ok else "[red]✗[/red]")
        console.print(table)
    finally:
        db.close()


@paper_app.command()
def status() -> None:
    """Показать состояние paper-счёта"""
    from src.trading.paper import PaperTradingEngine

    engine = PaperTradingEngine(user_id=0)
    state = engine.get_state()
    equity = state.total_equity()
    console.print("[bold cyan]Paper Trading Status[/bold cyan]")
    console.print(f"  Баланс: {state.balance:,.2f} ₽")
    console.print(f"  Начальный капитал: {state.initial_capital:,.2f} ₽")
    console.print(f"  Суммарная equity: {equity:,.2f} ₽")
    console.print(f"  Доходность: {((equity / state.initial_capital) - 1) * 100:+.2f}%")
    console.print(f"  Сделок: {len(state.trades)}")
    console.print(f"  Позиций: {len(state.positions)}")
    console.print(f"  Старт: {state.start_time}")
    if state.positions:
        console.print("\n[bold]Позиции:[/bold]")
        for p in sorted(state.positions.values(), key=lambda x: x.quantity * x.avg_price, reverse=True):
            console.print(f"  {p.ticker}: {p.quantity:.0f} × {p.avg_price:.2f} = {p.quantity * p.avg_price:,.2f} ₽")


@paper_app.command()
def metrics() -> None:
    """Показать метрики производительности paper-портфеля"""
    from src.trading.paper import PaperTradingEngine

    engine = PaperTradingEngine(user_id=0)
    m = engine.get_metrics()
    console.print("[bold cyan]Paper Trading Metrics[/bold cyan]")
    console.print(f"  Total Return: {m.total_return:+.2%}")
    console.print(f"  Annual Return: {m.annual_return:+.2%}")
    console.print(f"  Sharpe: {m.sharpe:.2f}")
    console.print(f"  Sortino: {m.sortino:.2f}")
    console.print(f"  Calmar: {m.calmar:.2f}")
    console.print(f"  Max Drawdown: {m.max_drawdown:.2%}")
    console.print(f"  Win Rate: {m.win_rate:.1%} ({m.n_wins}/{m.n_trades})")
    console.print(f"  Profit Factor: {m.profit_factor:.2f}")
    console.print(f"  VaR(95%): {m.var_95:.2%}")
    console.print(f"  Volatility: {m.volatility:.2%}")
