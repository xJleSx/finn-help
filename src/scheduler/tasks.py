import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.alerts.generators import generate_all_alerts, store_alerts
from src.analysis.rebalancing import RebalancingEngine
from src.analysis.service import analysis_service
from src.core.executor import get_executor
from src.db.connection import get_async_session
from src.db.models import Signal as SignalModel
from src.scheduler.collectors import (
    collect_alternative_data,
    collect_bond_offerings,
    collect_company_profiles,
    collect_corporate_events,
    collect_dividends,
    collect_financial_reports,
    collect_fundamental,
    collect_macro,
    collect_news,
    collect_prices,
    collect_social_posts,
    collect_social_sentiment,
    compute_geo_risk,
    compute_indicators,
    generate_signals,
    run_news_summarizer,
    run_sector_impact_analysis,
)
from src.signals.engine import SignalFusionEngine
from src.trading.brokers.sync import sync_portfolio_from_broker

logger = logging.getLogger(__name__)

fusion = SignalFusionEngine()

BATCH_SIZE = 50


async def _delete_today_signals(db: AsyncSession) -> None:
    from sqlalchemy import delete as sa_delete

    today = date.today()
    await db.execute(
        sa_delete(SignalModel).where(
            SignalModel.date >= today,
            SignalModel.date < today + timedelta(days=1),
        )
    )
    await db.commit()


async def _process_in_batches(items: list[Any], processor: Any, batch_size: int = BATCH_SIZE) -> list[Any]:
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        batch_results = await asyncio.gather(*[processor(item) for item in batch], return_exceptions=True)
        for item, result in zip(batch, batch_results):
            if isinstance(result, Exception):
                logger.warning("Batch processing failed for %s: %s", item, result)
                results.append(None)
            else:
                results.append(result)
    return results


async def daily_update() -> None:
    logger.info("Starting daily update cycle...")
    async with get_async_session() as db:
        try:
            updated_ids = await collect_prices(db)
            await collect_dividends(db)
            await collect_fundamental(db)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(get_executor(), lambda: compute_indicators(db, instrument_ids=updated_ids))
            news_list = await collect_news(db)
            await compute_geo_risk(db, news_list)
            await collect_macro(db)
            await collect_alternative_data(db)

            await collect_social_posts(db)
            await collect_social_sentiment()

            digest = await run_news_summarizer(db)
            if digest:
                logger.info("Daily digest (%d chars)", len(digest))

            await run_sector_impact_analysis(db)
            await collect_bond_offerings(db)

            sync_result = await sync_portfolio_from_broker(user_id=1)
            if sync_result.get("positions_synced", 0) > 0 or sync_result.get("removed", 0) > 0:
                logger.info(
                    "Portfolio synced: %d positions, %d removed",
                    sync_result["positions_synced"],
                    sync_result.get("removed", 0),
                )

            await _delete_today_signals(db)
            await generate_signals(db, updated_ids=None)
            logger.info("Daily update cycle completed")
        except Exception as e:
            logger.error("Daily update cycle failed: %s", e)
            await db.rollback()


async def weekly_update() -> None:
    """Weekly tasks: financial reports, bond offerings, company profiles, corporate events, alerts, rebalance."""
    logger.info("Starting weekly update cycle...")
    async with get_async_session() as db:
        loop = asyncio.get_running_loop()
        try:
            await collect_financial_reports(db)
            await loop.run_in_executor(get_executor(), collect_company_profiles, db)
            await collect_corporate_events(db)

            await loop.run_in_executor(
                get_executor(),
                lambda: analysis_service.train_models(db),
            )

            rebalancer = RebalancingEngine()
            plan = await loop.run_in_executor(get_executor(), lambda: rebalancer.analyze_portfolio(db, user_id=0))
            if plan:
                logger.info("Rebalance plan: %d actions", len(plan))

            alerts = await loop.run_in_executor(get_executor(), generate_all_alerts, db)
            stored = await loop.run_in_executor(get_executor(), store_alerts, db, alerts)
            if stored:
                logger.info("Alerts generated: %d new", stored)

            logger.info("Weekly update cycle completed")
        except Exception as e:
            logger.error("Weekly update cycle failed: %s", e)

    # Periodic model cleanup — runs even if weekly cycle partially fails
    try:
        from src.model_registry import prune_models as _prune_registry

        result = await loop.run_in_executor(get_executor(), _prune_registry)
        if result["registry_pruned"] or result["orphan_files_removed"]:
            logger.info("prune_models: %s", result)
    except Exception as e:
        logger.warning("prune_models failed: %s", e)
