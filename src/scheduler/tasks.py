import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from src.alerts.generators import generate_all_alerts, store_alerts
from src.analysis.rebalancing import RebalancingEngine
from src.analysis.service import analysis_service
from src.core.executor import get_executor
from src.db.connection import get_session
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


def _delete_today_signals_sync(db: Session) -> None:
    today = date.today()
    db.query(SignalModel).filter(
        SignalModel.date >= today,
        SignalModel.date < today + timedelta(days=1),
    ).delete()
    db.commit()


async def daily_update() -> None:
    logger.info("Starting daily update cycle...")
    db_sync = get_session()
    try:
        loop = asyncio.get_running_loop()
        updated_ids = await loop.run_in_executor(get_executor(), collect_prices, db_sync)
        await loop.run_in_executor(get_executor(), collect_dividends, db_sync)
        await loop.run_in_executor(get_executor(), collect_fundamental, db_sync)
        await loop.run_in_executor(get_executor(), lambda: compute_indicators(db_sync, instrument_ids=updated_ids))
        news_list = await loop.run_in_executor(get_executor(), collect_news, db_sync)
        await loop.run_in_executor(get_executor(), compute_geo_risk, db_sync, news_list)
        await loop.run_in_executor(get_executor(), collect_macro, db_sync)
        await loop.run_in_executor(get_executor(), collect_alternative_data, db_sync)
        await loop.run_in_executor(get_executor(), collect_social_posts, db_sync)
        await loop.run_in_executor(get_executor(), collect_social_sentiment)

        digest = await loop.run_in_executor(get_executor(), run_news_summarizer, db_sync)
        if digest:
            logger.info("Daily digest (%d chars)", len(digest))

        await loop.run_in_executor(get_executor(), run_sector_impact_analysis, db_sync)
        await loop.run_in_executor(get_executor(), collect_bond_offerings, db_sync)

        sync_result = await sync_portfolio_from_broker(user_id=1)
        if sync_result.get("positions_synced", 0) > 0 or sync_result.get("removed", 0) > 0:
            logger.info(
                "Portfolio synced: %d positions, %d removed",
                sync_result["positions_synced"],
                sync_result.get("removed", 0),
            )

        await loop.run_in_executor(get_executor(), _delete_today_signals_sync, db_sync)
        await loop.run_in_executor(get_executor(), lambda: generate_signals(db_sync, updated_ids=None))
        logger.info("Daily update cycle completed")
    except Exception as e:
        logger.error("Daily update cycle failed: %s", e)
        db_sync.rollback()
    finally:
        db_sync.close()


async def weekly_update() -> None:
    """Weekly tasks: financial reports, bond offerings, company profiles, corporate events, alerts, rebalance."""
    logger.info("Starting weekly update cycle...")
    loop = asyncio.get_running_loop()
    db_sync = get_session()
    try:
        await loop.run_in_executor(get_executor(), collect_financial_reports, db_sync)
        await loop.run_in_executor(get_executor(), collect_company_profiles, db_sync)
        await loop.run_in_executor(get_executor(), collect_corporate_events, db_sync)

        await loop.run_in_executor(
            get_executor(),
            lambda: analysis_service.train_models(db_sync),
        )

        rebalancer = RebalancingEngine()
        plan = await loop.run_in_executor(get_executor(), lambda: rebalancer.analyze_portfolio(db_sync, user_id=0))
        if plan:
            logger.info("Rebalance plan: %d actions", len(plan))

        alerts = await loop.run_in_executor(get_executor(), generate_all_alerts, db_sync)
        stored = await loop.run_in_executor(get_executor(), store_alerts, db_sync, alerts)
        if stored:
            logger.info("Alerts generated: %d new", stored)

        logger.info("Weekly update cycle completed")
    except Exception as e:
        logger.error("Weekly update cycle failed: %s", e)
    finally:
        db_sync.close()

    # Periodic model cleanup — runs even if weekly cycle partially fails
    try:
        from src.model_registry import prune_models as _prune_registry

        result = await loop.run_in_executor(get_executor(), _prune_registry)
        if result["registry_pruned"] or result["orphan_files_removed"]:
            logger.info("prune_models: %s", result)
    except Exception as e:
        logger.warning("prune_models failed: %s", e)
