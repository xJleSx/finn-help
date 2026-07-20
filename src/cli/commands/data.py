import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.cli.output import console
from src.collectors.cbr import CBRCollector
from src.collectors.financials import FinancialReportCollector
from src.collectors.moex import MOEXCollector
from src.db.connection import get_session
from src.db.models import BondOffering, Dividend, FinancialReport, Instrument, Price

from . import app

logger = logging.getLogger(__name__)


async def _update_ticker(moex: MOEXCollector, tk: str, itype: str = "stock") -> None:
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=tk).first()
        if not inst:
            market_data = await moex.get_marketdata(tk, itype=itype)
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

        board = {"stock": "stock", "bond": "bond", "etf": "etf"}.get(str(inst.instrument_type), "shares")
        last_date = db.query(Price.date).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
        from_date = (last_date[0] + timedelta(days=1)).isoformat() if last_date else (date.today() - timedelta(days=365)).isoformat()

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
                div_exists = db.query(Dividend).filter_by(instrument_id=inst.id, date=d, amount=float(amt)).first()
                if not div_exists:
                    div = Dividend(
                        instrument_id=inst.id,
                        date=d,
                        amount=float(amt),
                        currency="RUB",
                    )
                    db.add(div)
            db.commit()

        # Auto-fetch IFRS financial report for stocks
        if inst.instrument_type in ("stock", "etf"):
            try:
                frc = FinancialReportCollector()
                fin_data = await frc.fetch(tk)
                await frc.close()
                if fin_data and len(fin_data) > 2:  # more than just period_type + reporting_date
                    period_type = fin_data.pop("period_type", "FY")
                    reporting_date_str = fin_data.pop("reporting_date", None)
                    if reporting_date_str:
                        rdate = date.fromisoformat(reporting_date_str)
                        # Check if report for this date already exists
                        existing = db.query(FinancialReport).filter_by(instrument_id=inst.id, report_date=rdate, period_type=period_type).first()
                        if not existing:
                            fr = FinancialReport(instrument_id=inst.id, report_date=rdate, period_type=period_type)
                            for key, val in fin_data.items():
                                if hasattr(fr, key) and isinstance(val, (int, float)):
                                    setattr(fr, key, val)
                            db.add(fr)
                            db.commit()
                            logger.info("Financial report saved for %s (%s)", tk, reporting_date_str)
            except Exception as e:
                logger.warning("Failed to fetch financials for %s: %s", tk, e)
                db.rollback()

    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при обновлении {tk}: {e}")
    finally:
        db.close()


@app.command()
def update(ticker: Optional[str] = typer.Argument(None, help="Тикер (например, SBER)")) -> None:
    """Обновить данные с MOEX"""

    async def _run() -> None:
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
                    for s in stocks[:300]:
                        secid = s.get("SECID") or s.get("secid")
                        if secid:
                            await _update_ticker(moex, tk=secid, itype="stock")
                    p.update(task, description="[green]✓[/green] Акции обновлены")

                    task2 = p.add_task("Загрузка ETF...", total=None)
                    etfs = await moex.get_etfs()
                    p.update(task2, description=f"Загружено {len(etfs)} ETF")
                    for e in etfs[:50]:
                        secid = e.get("SECID") or e.get("secid")
                        if secid:
                            await _update_ticker(moex, tk=secid, itype="etf")
                    p.update(task2, description="[green]✓[/green] ETF обновлены")

                    task3 = p.add_task("Загрузка облигаций...", total=None)
                    bonds = await moex.get_bonds()
                    p.update(task3, description=f"Загружено {len(bonds)} облигаций")
                    for b in bonds[:50]:
                        secid = b.get("SECID") or b.get("secid")
                        if secid:
                            await _update_ticker(moex, tk=secid, itype="bond")
                    p.update(task3, description="[green]✓[/green] Облигации обновлены")

        console.print("[green]✓[/green] Данные обновлены")

    asyncio.run(_run())


@app.command()
def list_instruments(
    type_filter: str = typer.Option("stock", "--type", "-t", help="Тип: stock, bond, etf"),
) -> None:
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
def rates() -> None:
    """Получить курсы валют ЦБ РФ"""

    async def _run() -> None:
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
def macro() -> None:
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
            row = db.query(MacroIndicator).filter_by(indicator_type=indicator_type).order_by(MacroIndicator.date.desc()).first()
            if row:
                table.add_row(labels[indicator_type], str(row.value), str(row.date))
            else:
                table.add_row(labels[indicator_type], "—", "—")
        console.print(table)
    finally:
        db.close()


@app.command()
def sectors() -> None:
    """Показать распределение инструментов по секторам"""
    from src.constants import SECTOR_NAMES

    db = get_session()
    try:
        instruments = db.query(Instrument).all()
        sector_map: dict[str, int] = {}
        for inst in instruments:
            sector = SECTOR_NAMES.get(str(inst.ticker), str(inst.sector) if inst.sector else "Прочее")
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
def financials(
    ticker: str = typer.Argument(..., help="Тикер (например, SBER)"),
    period: str = typer.Option("Q1", "--period", "-p", help="Период: Q1, Q2, Q3, Q4, annual, ttm"),
    year: int = typer.Option(2026, "--year", "-y", help="Год отчёта"),
    net_profit: Optional[float] = typer.Option(None, "--net-profit", help="Чистая прибыль (RUB)"),
    revenue: Optional[float] = typer.Option(None, "--revenue", help="Выручка (RUB)"),
    net_interest_income: Optional[float] = typer.Option(None, "--interest-income", help="Чистые процентные доходы (RUB)"),
    total_assets: Optional[float] = typer.Option(None, "--assets", help="Активы (RUB)"),
    total_liabilities: Optional[float] = typer.Option(None, "--liabilities", help="Обязательства (RUB)"),
    total_equity: Optional[float] = typer.Option(None, "--equity", help="Собственный капитал (RUB)"),
    loan_portfolio: Optional[float] = typer.Option(None, "--loan-portfolio", help="Кредитный портфель (RUB)"),
    view: bool = typer.Option(False, "--view", "-v", help="Показать сохранённые отчёты"),
) -> None:
    """Добавить или посмотреть финансовую отчётность инструмента (МСФО/РСБУ)"""
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            console.print(f"[red]Инструмент {ticker} не найден[/red]")
            return

        if view:
            reports = db.query(FinancialReport).filter_by(instrument_id=inst.id).order_by(FinancialReport.report_date.desc()).all()
            if not reports:
                console.print(f"[yellow]Нет данных для {ticker}[/yellow]")
                return
            table = Table(title=f"📋 Отчётность {ticker.upper()}")
            table.add_column("Дата", style="cyan")
            table.add_column("Период", style="white")
            table.add_column("Чистая прибыль", style="yellow")
            table.add_column("Активы", style="yellow")
            table.add_column("Капитал", style="yellow")
            for r in reports:
                np_str = f"{r.net_profit:,.0f}" if r.net_profit else "—"
                ta_str = f"{r.total_assets:,.0f}" if r.total_assets else "—"
                te_str = f"{r.total_equity:,.0f}" if r.total_equity else "—"
                table.add_row(str(r.report_date), r.period_type, np_str, ta_str, te_str)
            console.print(table)
            return

        fields = [
            net_profit,
            revenue,
            net_interest_income,
            total_assets,
            total_liabilities,
            total_equity,
            loan_portfolio,
        ]
        if not any(fields):
            console.print("[red]Укажите хотя бы один финансовый показатель[/red]")
            console.print("Пример: finn financials SBER --net-profit 162.49e9 --assets 8620.3e9 --period Q1 --year 2026")
            return

        from datetime import date as dt_date

        report_date = dt_date(year, 1, 1)
        existing = db.query(FinancialReport).filter_by(instrument_id=inst.id, report_date=report_date, period_type=period).first()
        if existing:
            console.print("[yellow]Отчёт за этот период уже существует, обновляю...[/yellow]")

        report = existing or FinancialReport(
            instrument_id=inst.id,
            report_date=report_date,
            period_type=period,
        )
        field_map = {
            "net_profit": net_profit,
            "revenue": revenue,
            "net_interest_income": net_interest_income,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "loan_portfolio": loan_portfolio,
        }
        for field_name, val in field_map.items():
            if val is not None:
                setattr(report, field_name, val)

        db.add(report)
        db.commit()
        console.print(f"[green]✓ Отчётность {ticker} ({period} {year}) сохранена[/green]")
    finally:
        db.close()


@app.command()
def bond(
    ticker: str = typer.Argument(..., help="Тикер облигации (например, SU26238RMFS5)"),
    coupon_type: str = typer.Option("fixed", "--coupon-type", "-t", help="Тип купона: fixed, floater, zero"),
    coupon_rate: Optional[float] = typer.Option(None, "--coupon", "-c", help="Ставка купона % годовых"),
    coupon_period: Optional[int] = typer.Option(None, "--period-days", "-d", help="Купонный период в днях"),
    spread: Optional[float] = typer.Option(None, "--spread", "-s", help="Спред к ключевой ставке (для флоатера)"),
    ytm: Optional[float] = typer.Option(None, "--ytm", help="YTM — доходность к погашению %"),
    maturity_years: Optional[float] = typer.Option(None, "--maturity", "-m", help="Срок обращения в годах"),
    rating: Optional[str] = typer.Option(None, "--rating", "-r", help="Кредитный рейтинг (AAA, AA, A, BBB)"),
    volume: Optional[float] = typer.Option(None, "--volume", help="Объём выпуска (RUB)"),
    amortization: bool = typer.Option(False, "--amortization", "-a", help="Амортизация"),
    offer: bool = typer.Option(False, "--offer", "-o", help="Оферта"),
    min_lot: Optional[float] = typer.Option(None, "--min-lot", "-l", help="Минимальная заявка (RUB)"),
    qual_only: bool = typer.Option(False, "--qual", "-q", help="Только для квал. инвесторов"),
    isin: Optional[str] = typer.Option(None, "--isin", help="ISIN выпуска"),
    view: bool = typer.Option(False, "--view", "-v", help="Показать сохранённые параметры"),
) -> None:
    """Добавить или посмотреть параметры облигации"""
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            console.print(f"[red]Инструмент {ticker} не найден[/red]")
            return

        if view:
            offerings = db.query(BondOffering).filter_by(instrument_id=inst.id).order_by(BondOffering.offering_date.desc()).all()
            if not offerings:
                console.print(f"[yellow]Нет данных для {ticker}[/yellow]")
                return
            table = Table(title=f"📋 Облигация {ticker.upper()}")
            table.add_column("ISIN", style="cyan")
            table.add_column("Купон", style="yellow")
            table.add_column("Ставка", style="yellow")
            table.add_column("Рейтинг", style="white")
            table.add_column("Срок", style="white")
            table.add_column("Мин. заявка", style="yellow")
            for o in offerings:
                coupon_str = f"{o.coupon_rate:.2f}%" if o.coupon_rate else "—"
                rating_str = o.credit_rating or "—"
                mat_str = f"{o.maturity_years:.1f}г" if o.maturity_years else "—"
                lot_str = f"{o.min_lot_rub:,.0f}" if o.min_lot_rub else "—"
                table.add_row(o.isin or "—", o.coupon_type, coupon_str, rating_str, mat_str, lot_str)
            console.print(table)
            return

        if not any([coupon_rate, spread, ytm, rating]):
            console.print("[red]Укажите хотя бы один параметр облигации[/red]")
            console.print("Пример: finn bond SU26238RMFS5 --coupon 17.41 --rating AAA --maturity 2.5 --min-lot 1400000")
            return

        offering = BondOffering(
            instrument_id=inst.id,
            offering_date=date.today(),
            isin=isin or inst.isin or "",
            coupon_type=coupon_type,
            coupon_rate=coupon_rate,
            coupon_period_days=coupon_period or 30,
            spread_to_key_rate=spread,
            yield_to_maturity=ytm,
            maturity_years=maturity_years,
            credit_rating=rating,
            volume=volume,
            has_amortization=amortization,
            has_offer=offer,
            min_lot_rub=min_lot,
            qual_investor_only=qual_only,
        )
        db.add(offering)
        db.commit()
        console.print(f"[green]✓ Параметры облигации {ticker} сохранены[/green]")
    finally:
        db.close()


@app.command()
def scan(ticker: str = typer.Argument(..., help="Тикер для массового поиска")) -> None:
    """Найти и добавить все тикеры, содержащие строку (например: SBER, GAZP, VTBR)"""

    async def _run() -> None:
        async with MOEXCollector() as moex:
            with console.status("Поиск инструментов..."):
                stocks = await moex.get_stocks()
                etfs = await moex.get_etfs()
                bonds = await moex.get_bonds()

            matches = [
                s
                for s in stocks + etfs + bonds
                if ticker.upper() in str(s.get("SECID", "")).upper() or ticker.upper() in str(s.get("SHORTNAME", "")).upper()
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
