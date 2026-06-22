import asyncio

import typer
from rich.console import Console
from rich.table import Table

console = Console()

social_app = typer.Typer(help="Social sentiment commands (Pulse, Telegram, etc.)")


@social_app.command(name="update")
def social_update():
    """Collect new posts from all active social sources"""
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
                        exists = (
                            db.query(SocialPost).filter_by(source=post.source, external_id=post.external_id).first()
                        )
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


@social_app.command(name="snapshot")
def social_snapshot(period: str = typer.Argument("daily", help="daily / weekly / monthly")):
    """Принудительно снять срез метрик и сформировать отчёт"""

    async def _run():
        from src.scheduler.reporting import generate_daily_report, take_snapshot

        console.print(f"[bold]📸 Снятие среза: {period}[/bold]")
        await take_snapshot(period)
        console.print(f"[green]✓[/green] Срез {period} сохранён")
        if period == "daily":
            report = await generate_daily_report()
            if report:
                console.print(report.report_text)

    asyncio.run(_run())


@social_app.command(name="report")
def social_report():
    """Сформировать ежедневный отчёт (без рассылки)"""

    async def _run():
        from src.scheduler.reporting import generate_daily_report

        console.print("[bold]📄 Генерация отчёта...[/bold]")
        report = await generate_daily_report()
        if report:
            console.print(report.report_text)
        else:
            console.print("[yellow]Отчёт не сформирован[/yellow]")

    asyncio.run(_run())
