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

from src.analysis.personal_backtest import run_personal_backtest
from src.analysis.service import analysis_service
from src.collectors.cbr import CBRCollector
from src.collectors.moex import MOEXCollector
from src.config import personal
from src.db.connection import get_session, init_db
from src.db.models import Dividend, GeoRiskScore, Indicator, Instrument, News, Portfolio, Price
from src.llm.router import llm
from src.signal.engine import compute_risk_metrics

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


async def _update_ticker(moex: MOEXCollector, tk: str, itype: str = "stock"):
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
        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices) < 50:
            return None, f"Недостаточно данных для {ticker}"
        ind_rows = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date).all()
        if len(ind_rows) < 2:
            return None, f"Недостаточно индикаторов для {ticker}"

        pdf = pd.DataFrame(
            [
                {"date": p.date, "open": p.open, "high": p.high, "low": p.low, "close": p.close, "volume": p.volume}
                for p in prices
            ]
        )
        idf = pd.DataFrame(
            [
                {
                    "date": r.date,
                    "rsi": r.rsi,
                    "macd_line": r.macd_line,
                    "macd_signal": r.macd_signal,
                    "macd_hist": r.macd_hist,
                    "sma_20": r.sma_20,
                    "sma_50": r.sma_50,
                    "sma_200": r.sma_200,
                    "bb_upper": r.bb_upper,
                    "bb_lower": r.bb_lower,
                    "bb_mid": r.bb_mid,
                    "volume_sma_20": r.volume_sma_20,
                    "atr": r.atr,
                }
                for r in ind_rows
            ]
        )
        idf = idf.merge(pdf[["date", "close"]], on="date", how="left")

        tech_signal = analysis_service.analyzer.generate_signal(idf)
        divs = db.query(Dividend).filter_by(instrument_id=inst.id).all()
        div_df = pd.DataFrame([{"date": d.date, "amount": d.amount} for d in divs])
        fund = analysis_service.fundamental.analyze(pdf, div_df)
        ml = analysis_service._compute_ml(pdf, idf, ticker=ticker.upper()) if with_ml else None
        geo_row = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        geo = {"score": geo_row.score} if geo_row else {"score": 0.0}

        from src.collectors.macro import MacroCollector

        macro_context = MacroCollector.latest_values(db)

        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        news_recent = db.query(News).filter(News.created_at >= cutoff).all()
        if news_recent:
            scores = [float(n.sentiment_weighted or n.sentiment_score or 0) for n in news_recent]
            mean = sum(scores) / len(scores)
            variance = sum((s - mean) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0.0
            sentiment = {
                "score": round(mean, 3),
                "divergence": round(min(variance * 2, 1.0), 3),
                "source": "rss",
                "count": len(scores),
            }
        else:
            sentiment = {"score": 0.0, "divergence": 0.0, "source": "none"}

        volatility_regime = analysis_service.volatility.detect(pdf, idf)
        risk_metrics = compute_risk_metrics(pdf["close"].tolist())
        mtf_data = analysis_service.mtf.compute_all(pdf)
        mtf_concordance = analysis_service.mtf.concordance(mtf_data) if mtf_data else None

        fused = analysis_service.fusion.fuse(
            ticker=ticker.upper(),
            technical=tech_signal,
            fundamental=fund,
            geo=geo,
            ml_prediction=ml,
            volatility_regime=volatility_regime,
            risk_metrics=risk_metrics,
            macro_context=macro_context,
            sentiment=sentiment,
            mtf=mtf_concordance,
        )

        if with_llm:
            advice = await llm.advise(fused)
        else:
            advice = ""

        return fused, advice
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
    from src.constants import SECTOR_NAMES

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
def train_models(
    ticker: Optional[str] = typer.Argument(None, help="Тикер (например, SBER), все если не указан"),
):
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


@app.command()
def full_cycle():
    """Полный цикл: update → train → backtest → report"""
    from datetime import datetime, timezone

    console.print("[bold]🚀 Запуск полного цикла[/bold]")
    start = datetime.now(timezone.utc)

    # 1. Update data
    console.print("\n[bold cyan]1/4 Обновление данных...[/bold cyan]")
    import asyncio

    async def _update():
        async with MOEXCollector() as moex:
            tickers = personal.get("favorite_tickers", ["SBER", "LKOH", "GAZP", "YNDX", "TATN"])
            for t in tickers:
                await moex.get_history(t, days=365)
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
    except Exception:
        pass


@app.command()
def bot():
    """Запустить Telegram бота"""
    from src.interfaces.telegram import run_bot

    asyncio.run(run_bot())


@app.command()
def scheduler():
    """Запустить фоновый scheduler (обновление каждый час)"""
    from src.scheduler.service import run_forever

    asyncio.run(run_forever())


social_app = typer.Typer(help="Social sentiment commands (Pulse, Telegram, etc.)")
app.add_typer(social_app, name="social")


@social_app.command(name="update")
def social_update():
    """Collect new posts from all active social sources"""
    import asyncio

    from src.social.registry import registry
    from src.social.sentiment.analyzer import analyzer

    async def _run():
        registry.build_from_config()
        sources = registry.get_active()
        if not sources:
            console.print("[yellow]No active social sources. Configure in data/personal_settings.yaml[/yellow]")
            return

        from src.db.connection import get_session
        from src.db.models import SocialPost

        console.print(f"[bold]Collecting from {len(sources)} source(s)...[/bold]")
        for src in sources:
            console.print(f"  Collecting from [cyan]{src.source_name}[/cyan]...")
            try:
                posts = await src.fetch_posts()
                db = get_session()
                try:
                    new_count = 0
                    for post in posts:
                        exists = db.query(SocialPost).filter_by(
                            source=post.source, external_id=post.external_id
                        ).first()
                        if exists:
                            continue
                        sp = SocialPost(
                            source=post.source,
                            external_id=post.external_id,
                            author_nick=post.author_nick,
                            author_id=post.author_id,
                            text=post.text,
                            published_at=post.published_at,
                            url=post.url,
                            tickers_mentioned=post.tickers,
                            raw_json=post.raw,
                        )
                        db.add(sp)
                        new_count += 1
                    db.commit()
                    console.print(f"    [green]✓[/green] {new_count} new posts saved")
                finally:
                    db.close()
            except Exception as e:
                console.print(f"    [red]✗[/red] {e}")

        console.print("\n[bold]Analyzing new posts with LLM...[/bold]")
        count = await analyzer.process_new_posts()
        console.print(f"  [green]✓[/green] {count} sentiment signals created")

    asyncio.run(_run())


@social_app.command(name="ticker")
def social_ticker(ticker: str = typer.Argument(..., help="Ticker (e.g. SBER)")):
    """Show social sentiment for a ticker"""
    from src.social.sentiment.aggregator import aggregator

    result = aggregator.get_ticker_sentiment(ticker.upper())
    if result["count"] == 0:
        console.print(f"[yellow]No social data for {ticker.upper()}[/yellow]")
        return

    table = Table(title=f"Social Sentiment — {ticker.upper()}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="yellow")
    table.add_row("Score", f"{result['score']:.3f}")
    table.add_row("Divergence", f"{result['divergence']:.3f}")
    table.add_row("Posts analyzed", str(result["count"]))
    table.add_row("Avg confidence", f"{result.get('avg_confidence', 0):.3f}")
    console.print(table)


@social_app.command(name="overview")
def social_overview(days: int = typer.Option(1, "--days", "-d", help="Days to look back")):
    """Show market overview from social sentiment"""
    from src.social.sentiment.aggregator import aggregator

    overview = aggregator.get_market_overview(days=days)
    if not overview:
        console.print("[yellow]No social data for the period[/yellow]")
        return

    table = Table(title=f"Social Market Overview (last {days}d)")
    table.add_column("Ticker", style="cyan")
    table.add_column("Avg Score", style="yellow")
    table.add_column("Volume", style="white")
    for row in overview[:20]:
        ticker = row["ticker"] or "Market (general)"
        table.add_row(ticker, f"{row['avg_score']:.3f}", str(row["volume"]))
    console.print(table)


def main():
    app()
