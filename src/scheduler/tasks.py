import asyncio
import logging
from datetime import date

from sqlalchemy import func

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
from src.signal.engine import SignalFusionEngine
from src.trading.brokers.sync import sync_portfolio_from_broker

logger = logging.getLogger(__name__)

fusion = SignalFusionEngine()


async def daily_update() -> None:
    logger.info("Starting daily update cycle...")
    db = get_session()

    try:
        updated_ids = await collect_prices(db)
        await collect_dividends(db)
        await collect_fundamental(db)
        compute_indicators(db, instrument_ids=updated_ids)
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

        sync_result = await sync_portfolio_from_broker()
        if sync_result.get("positions_synced", 0) > 0 or sync_result.get("removed", 0) > 0:
            logger.info(
                "Portfolio synced: %d positions, %d removed",
                sync_result["positions_synced"],
                sync_result.get("removed", 0),
            )

        db.query(SignalModel).filter(func.date(SignalModel.date) == date.today()).delete()
        db.commit()
        await generate_signals(db, updated_ids=None)
        logger.info("Daily update cycle completed")
    except Exception as e:
        logger.error(f"Daily update cycle failed: {e}")
    finally:
        db.close()


def run_daily_sync() -> None:
    asyncio.run(daily_update())


async def weekly_update() -> None:
    """Weekly tasks: financial reports, bond offerings, company profiles, corporate events, alerts, rebalance."""
    logger.info("Starting weekly update cycle...")
    db = get_session()
    try:
        await collect_financial_reports(db)
        await collect_bond_offerings(db)
        await collect_company_profiles(db)
        await collect_corporate_events(db)

        from src.analysis.rebalancing import RebalancingEngine

        rebalancer = RebalancingEngine()
        plan = rebalancer.analyze_portfolio(db, user_id=0)
        if plan:
            logger.info("Rebalance plan: %d actions", len(plan))

        from src.alerts.generators import generate_all_alerts, store_alerts

        alerts = generate_all_alerts(db)
        stored = store_alerts(db, alerts)
        if stored:
            logger.info("Alerts generated: %d new", stored)

        logger.info("Weekly update cycle completed")
    except Exception as e:
        logger.error(f"Weekly update cycle failed: {e}")
    finally:
        db.close()
