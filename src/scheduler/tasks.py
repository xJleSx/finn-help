import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete

from src.alerts.generators import async_generate_all_alerts, async_store_alerts
from src.analysis.fundamental.base import async_refresh_sector_benchmarks
from src.analysis.rebalancing import async_analyze_portfolio
from src.db.connection import get_async_session
from src.db.models import Signal as SignalModel
from src.model_registry import async_prune_models
from src.scheduler.collectors import (
    async_collect_company_profiles,
    async_compute_indicators,
    collect_alternative_data,
    collect_bond_offerings,
    collect_corporate_events,
    collect_discover_bonds,
    collect_dividends,
    collect_financial_reports,
    collect_fundamental,
    collect_macro,
    collect_news,
    collect_prices,
    collect_social_posts,
    collect_social_sentiment,
    compute_geo_risk,
    generate_signals,
    run_news_summarizer,
    run_sector_impact_analysis,
)
from src.signals.engine import SignalFusionEngine
from src.trading.brokers.sync import sync_portfolio_from_broker

logger = logging.getLogger(__name__)

fusion = SignalFusionEngine()

BATCH_SIZE = 50


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
    """Run the daily update cycle — prices, dividends, news, signals.

    When updated_ids is None, signals are regenerated for all instruments.
    Pass a list of instrument IDs to only generate signals for changed instruments.
    """
    logger.info("Starting daily update cycle...")
    async with get_async_session() as db:
        try:
            updated_ids = await collect_prices(db)
            await collect_dividends(db)
            await collect_fundamental(db)
            await async_compute_indicators(instrument_ids=updated_ids)
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
            await collect_discover_bonds(db)
            await collect_bond_offerings(db)

            await async_refresh_sector_benchmarks()

            from src.config import personal
            sync_cfg = personal.get("sync", {})
            default_user_id = sync_cfg.get("default_user_id") if isinstance(sync_cfg, dict) else None
            sync_user_id = int(default_user_id) if default_user_id else 1
            sync_result = await sync_portfolio_from_broker(user_id=sync_user_id)
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


async def _delete_today_signals(db: Any) -> None:
    today = date.today()
    await db.execute(
        delete(SignalModel).where(
            SignalModel.date >= today,
            SignalModel.date < today + timedelta(days=1),
        )
    )
    await db.commit()


async def weekly_update() -> None:
    """Weekly tasks: financial reports, bond offerings, company profiles, corporate events, alerts, rebalance."""
    logger.info("Starting weekly update cycle...")
    async with get_async_session() as db:
        try:
            await collect_financial_reports(db)
            await async_collect_company_profiles()
            await collect_corporate_events(db)

            from src.analysis.service import analysis_service

            await analysis_service.train_models_async()

            plan = await async_analyze_portfolio(user_id=0)
            if plan:
                logger.info("Rebalance plan: %d actions", len(plan))

            alerts = await async_generate_all_alerts()
            stored = await async_store_alerts(alerts)
            if stored:
                logger.info("Alerts generated: %d new", stored)

            logger.info("Weekly update cycle completed")
        except Exception as e:
            logger.error("Weekly update cycle failed: %s", e)

    # Periodic model cleanup — runs even if weekly cycle partially fails
    try:
        result = await async_prune_models()
        if result["registry_pruned"] or result["orphan_files_removed"]:
            logger.info("prune_models: %s", result)
    except Exception as e:
        logger.warning("prune_models failed: %s", e)


async def collect_prices_background() -> None:
    logger.info("Collecting prices...")
    async with get_async_session() as db:
        try:
            updated = await collect_prices(db)
            logger.info("Prices collected: %d instruments updated", len(updated))
        except Exception as e:
            logger.error("Price collection failed: %s", e)


async def generate_signals_background() -> None:
    logger.info("Generating signals...")
    async with get_async_session() as db:
        try:
            await generate_signals(db, instrument_ids=None)
            logger.info("Signals generated")
        except Exception as e:
            logger.error("Signal generation failed: %s", e)


async def train_models_background() -> None:
    logger.info("Training ML models...")
    try:
        from src.analysis.service import analysis_service
        await analysis_service.train_models_async()
        logger.info("Model training completed")
    except Exception as e:
        logger.error("Model training failed: %s", e)


async def clear_stale_feature_cache_background() -> None:
    from src.analysis.market.feature_store import clear_stale
    count = clear_stale(max_age_days=7)
    logger.info("Cleared %d stale feature cache entries", count)
