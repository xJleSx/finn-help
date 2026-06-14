import asyncio
import logging
import sys
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.analysis.service import analysis_service
from src.collectors.cbr import CBRCollector
from src.collectors.moex import MOEXCollector
from src.db.connection import get_session, init_db
from src.db.models import Dividend, Instrument, Portfolio, Price

if sys.stdout.encoding != "utf-8" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

console = Console()
app = typer.Typer(help="FinAdvisor — AI финансовый ассистент для MOEX")
logger = logging.getLogger(__name__)


@app.callback()
def callback():
    pass


@app.command()
def init():
    """Инициализировать базу данных"""
    init_db()
    console.print("[green]OK[/green] База данных инициализирована")


@app.command()
def update(ticker: Optional[str] = typer.Argument(None, help="Тикер (например, SBER)")):
    """Обновить данные с MOEX"""

    async def _run():
        async with MOEXCollector() as moex:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as p:
                if ticker:
                    task = p.add_task(f"Загрузка {ticker}...", total=None)
                    await _update_ticker(moex, tk=ticker.upper())
                    p.update(task, description=f"[green]✓[/green] {ticker} обновлён")
                else:
                    task = p.add_task("Загрузка списка акций...", total=None)
                    stocks = await moex.get_stocks()
                    p.update(task, description=f"Загружено {len(stocks)} акций")
                    for s in stocks[:50]:
                        secid = s.get("SECID") or s.get("secid")
                        if secid:
                            await _update_ticker(moex, tk=secid, itype="stock")
                    p.update(task, description="[green]✓[/green] Акции обновлены")

                    task2 = p.add_task("Загрузка ETF...", total=None)
                    etfs = await moex.get_etfs()
                    p.update(task2, description=f"Загружено {len(etfs)} ETF")
                    for e in etfs[:20]:
                        secid = e.get("SECID") or e.get("secid")
                        if secid:
                            await _update_ticker(moex, tk=secid, itype="etf")
                    p.update(task2, description="[green]✓[/green] ETF обновлены")

                    task3 = p.add_task("Загрузка облигаций...", total=None)
                    bonds = await moex.get_bonds()
                    p.update(task3, description=f"Загружено {len(bonds)} облигаций")
                    for b in bonds[:10]:
                        secid = b.get("SECID") or b.get("secid")
                        if secid:
                            await _update_ticker(moex, tk=secid, itype="bond")
                    p.update(task3, description="[green]✓[/green] Облигации обновлены")

        console.print("[green]✓[/green] Данные обновлены")

    asyncio.run(_run())


async def _update_ticker(moex: MOEXCollector, tk: str, itype: str = "stock"):
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=tk).first()
        if not inst:
            market_data = await moex.get_marketdata(tk)
            if not market_data:
                logger.warning(f"Не удалось найти {tk} на MOEX")
                return
            inst = Instrument(
                ticker=tk,
                full_name=market_data.get("SHORTNAME", tk),
                instrument_type=itype,
                lot_size=market_data.get("LOTSIZE", 1),
            )
            db.add(inst)
            db.commit()

        board = {"stock": "stock", "bond": "bond", "etf": "etf"}.get(inst.instrument_type, "shares")
        last_date = db.query(Price.date).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
        from_date = (
            (last_date[0] + timedelta(days=1)).isoformat()
            if last_date
            else (date.today() - timedelta(days=365)).isoformat()
        )

        history = await moex.get_history(tk, from_date=from_date, board=board)
        if not history:
            logger.info(f"Нет новых данных для {tk}")
        else:
            for row in history:
                d = row.get("TRADEDATE") or row.get("tradedate")
                if not d:
                    continue
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                exists = db.query(Price).filter_by(instrument_id=inst.id, date=d).first()
                if not exists:
                    price = Price(
                        instrument_id=inst.id,
                        date=d,
                        open=row.get("OPEN") or row.get("open"),
                        high=row.get("HIGH") or row.get("high"),
                        low=row.get("LOW") or row.get("low"),
                        close=row.get("CLOSE") or row.get("close"),
                        volume=row.get("VOLUME") or row.get("volume"),
                    )
                    db.add(price)
            db.commit()

        if inst.instrument_type in ("stock", "etf"):
            dividends = await moex.get_dividends(tk)
            for row in dividends:
                d = row.get("registryclosedate") or row.get("recordDate") or row.get("recorddate")
                amt = row.get("value") or row.get("dividendGross")
                if not d or not amt:
                    continue
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                exists = db.query(Dividend).filter_by(instrument_id=inst.id, date=d, amount=float(amt)).first()
                if not exists:
                    div = Dividend(
                        instrument_id=inst.id,
                        date=d,
                        amount=float(amt),
                        currency="RUB",
                    )
                    db.add(div)
            db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при обновлении {tk}: {e}")
    finally:
        db.close()


async def run_analysis(ticker: str, with_llm: bool = True, with_ml: bool = True) -> tuple[dict, str]:
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            return None, f"Инструмент {ticker} не найден"
        return await analysis_service.analyze_with_advice(db, inst, ticker, with_ml=with_ml)
    finally:
        db.close()


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="Тикер (например, SBER)"),
    with_llm: bool = typer.Option(True, "--llm/--no-llm", help="Использовать LLM для совета"),
):
    """Проанализировать инструмент"""

    async def _run():
        db = get_session()
        try:
            inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
            if not inst:
                console.print(f"[red]✗[/red] Инструмент {ticker} не найден")
                return

            prices_q = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
            if not prices_q:
                console.print(f"[red]✗[/red] Нет данных для {ticker}")
                return

            with Progress(console=console) as p:
                p.add_task("Анализ...", total=None)
                fused, advice = await run_analysis(ticker, with_llm)

            if not fused:
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
                    f"[bold]{fused['action']}[/bold] (уверенность: {fused['confidence']:.0%})",
                )
                table.add_row("Макс. доля", f"до {fused['max_portfolio_pct']}% портфеля")

            console.print(table)

            if advice:
                console.print(f"\n[bold]🤖 Совет:[/bold]\n{advice}")

        finally:
            db.close()

    asyncio.run(_run())


@app.command()
def list_instruments(
    type_filter: str = typer.Option("stock", "--type", "-t", help="Тип: stock, bond, etf"),
):
    """Список инструментов в базе"""
    db = get_session()
    try:
        instruments = db.query(Instrument).filter_by(instrument_type=type_filter).order_by(Instrument.ticker).all()
        if not instruments:
            console.print(f"Нет инструментов типа {type_filter}. Выполните: finn update")
            return

        table = Table(title=f"📋 {type_filter.upper()} — {len(instruments)} шт.")
        table.add_column("Тикер", style="cyan")
        table.add_column("Название", style="white")
        table.add_column("Цена", style="yellow")

        for inst in instruments:
            last_price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
            price_str = f"{last_price.close:.2f}" if last_price and last_price.close else "—"
            table.add_row(inst.ticker, inst.full_name or "—", price_str)

        console.print(table)
    finally:
        db.close()


@app.command()
def rates():
    """Получить курсы валют ЦБ РФ"""

    async def _run():
        console.print("[bold]🏦 Курсы валют (ЦБ РФ):[/bold]")
        try:
            cbr = CBRCollector()
            rates = await cbr.get_rates()
            table = Table()
            table.add_column("Код", style="cyan")
            table.add_column("Валюта", style="white")
            table.add_column("Курс", style="yellow")
            for r in rates:
                table.add_row(r["code"], r["name"], f"{r['value']:.2f} ₽")
            console.print(table)
        except Exception as e:
            console.print(f"[red]Ошибка получения курсов ЦБ: {e}[/red]")

    asyncio.run(_run())


@app.command()
def macro():
    """Показать последние макро-индикаторы (Brent, ключевая ставка, USD/RUB, IMOEX, CPI, ОФЗ, M2)"""
    from src.db.models import MacroIndicator

    db = get_session()
    try:
        table = Table(title="📈 Макро-индикаторы")
        table.add_column("Индикатор", style="cyan")
        table.add_column("Значение", style="yellow")
        table.add_column("Дата", style="white")
        labels = {
            "brent": "Brent ($/bbl)",
            "key_rate": "Ключевая ставка ЦБ (%)",
            "usd_rate": "USD/RUB",
            "imoex": "IMOEX (пункты)",
            "cpi": "Инфляция CPI (%)",
            "ofz_10y": "ОФЗ 10Y (%)",
            "m2": "M2 (млрд руб)",
        }
        for indicator_type in labels:
            row = (
                db.query(MacroIndicator)
                .filter_by(indicator_type=indicator_type)
                .order_by(MacroIndicator.date.desc())
                .first()
            )
            if row:
                table.add_row(labels[indicator_type], str(row.value), str(row.date))
            else:
                table.add_row(labels[indicator_type], "—", "—")
        console.print(table)
    finally:
        db.close()


@app.command()
def sectors():
    """Показать распределение инструментов по секторам"""
    from src.portfolio.allocator import SECTOR_NAMES

    db = get_session()
    try:
        instruments = db.query(Instrument).all()
        sector_map: dict[str, int] = {}
        for inst in instruments:
            sector = SECTOR_NAMES.get(inst.ticker, inst.sector or "Прочее")
            sector_map[sector] = sector_map.get(sector, 0) + 1

        table = Table(title="🏭 Распределение по секторам")
        table.add_column("Сектор", style="cyan")
        table.add_column("Количество", style="yellow")
        total = 0
        for sector, count in sorted(sector_map.items(), key=lambda x: -x[1]):
            table.add_row(sector, str(count))
            total += count
        table.add_row("[bold]Итого[/bold]", str(total))
        console.print(table)
    finally:
        db.close()


@app.command()
def auto():
    """Запустить полный цикл: обновить ВСЕ MOEX + анализ + сигналы"""

    async def _run():
        from src.scheduler.tasks import daily_update

        console.print("[bold]🚀 Запуск автономного цикла...[/bold]")
        await daily_update()
        console.print("[green]✓[/green] Цикл завершён. Все инструменты проанализированы.")

    asyncio.run(_run())


@app.command()
def scan(ticker: str = typer.Argument(..., help="Тикер для массового поиска")):
    """Найти и добавить все тикеры, содержащие строку (например: SBER, GAZP, VTBR)"""

    async def _run():
        async with MOEXCollector() as moex:
            with console.status("Поиск инструментов..."):
                stocks = await moex.get_stocks()
                etfs = await moex.get_etfs()
                bonds = await moex.get_bonds()

            matches = [
                s
                for s in stocks + etfs + bonds
                if ticker.upper() in str(s.get("SECID", "")).upper()
                or ticker.upper() in str(s.get("SHORTNAME", "")).upper()
            ]

            if not matches:
                console.print(f"Ничего не найдено по запросу '{ticker}'")
                return

            table = Table(title=f"Найдено {len(matches)} инструментов")
            table.add_column("Тикер", style="cyan")
            table.add_column("Название")
            table.add_column("Тип")

            for m in matches[:30]:
                secid = m.get("SECID") or m.get("secid", "?")
                name = m.get("SHORTNAME") or m.get("shortname", "?")
                table.add_row(secid, name, "акция")

            console.print(table)
            console.print(f"\nЧтобы загрузить: finn update {matches[0].get('SECID', 'TICKER')}")

    asyncio.run(_run())


@app.command()
def seed_portfolio(
    reset: bool = typer.Option(False, "--reset", help="Сбросить и пересоздать"),
):
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
def bot():
    """Запустить Telegram бота"""
    from src.interfaces.telegram import run_bot

    asyncio.run(run_bot())


def main():
    app()
