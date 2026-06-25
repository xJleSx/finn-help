import asyncio
import logging
from datetime import date

from sqlalchemy import func

from src.db.connection import get_session
from src.db.models import Signal as SignalModel
from src.scheduler.collectors import (
    collect_dividends,
    collect_fundamental,
    collect_macro,
    collect_news,
    collect_prices,
    collect_social_sentiment,
    compute_geo_risk,
    compute_indicators,
    generate_signals,
)
from src.signal.engine import SignalFusionEngine
from src.trading.brokers.sync import sync_portfolio_from_broker

logger = logging.getLogger(__name__)

fusion = SignalFusionEngine()


async def daily_update():
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

        await collect_social_sentiment()

        sync_result = await sync_portfolio_from_broker()
        if sync_result.get("positions_synced", 0) > 0 or sync_result.get("removed", 0) > 0:
            logger.info("Portfolio synced: %d positions, %d removed", sync_result["positions_synced"], sync_result.get("removed", 0))

        db.query(SignalModel).filter(func.date(SignalModel.date) == date.today()).delete()
        db.commit()
        await generate_signals(db, updated_ids=None)
        logger.info("Daily update cycle completed")
    except Exception as e:
        logger.error(f"Daily update cycle failed: {e}")
    finally:
        db.close()


def run_daily_sync():
    asyncio.run(daily_update())
