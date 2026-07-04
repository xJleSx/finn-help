from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func

from src.tasks import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=3, default_retry_delay=60, name="train_model")
def train_model(self, instrument_id: int, ticker: str) -> dict[str, Any]:
    """Train all ML models for a single instrument as a background task."""
    from src.db.connection import get_session
    from src.db.models import Instrument

    logger.info("Training models for %s (id=%d)", ticker, instrument_id)
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(id=instrument_id).first()
        if not inst:
            return {"ticker": ticker, "status": "error", "error": "Instrument not found"}

        from src.analysis.ml.ensemble import EnsembleModel
        from src.analysis.ml.news_impact import NewsImpactModel
        from src.analysis.ml.prophet_model import ProphetModel

        results: dict[str, Any] = {"ticker": ticker, "models": {}}

        try:
            prophet = ProphetModel(ticker)
            prophet.train(db)
            results["models"]["prophet"] = "ok"
        except Exception as e:
            logger.warning("Prophet training failed for %s: %s", ticker, e)
            results["models"]["prophet"] = str(e)

        try:
            ensemble = EnsembleModel(ticker)
            ensemble.train(db)
            results["models"]["ensemble"] = "ok"
        except Exception as e:
            logger.warning("Ensemble training failed for %s: %s", ticker, e)
            results["models"]["ensemble"] = str(e)

        try:
            impact = NewsImpactModel(ticker)
            for horizon in impact.horizons:
                try:
                    impact.train(horizon)
                    results["models"][f"news_impact_{horizon}d"] = "ok"
                except Exception as e:
                    logger.warning("News impact training failed for %s horizon=%d: %s", ticker, horizon, e)
                    results["models"][f"news_impact_{horizon}d"] = str(e)
        except Exception as e:
            logger.warning("News impact init failed for %s: %s", ticker, e)

        results["status"] = "ok"
        logger.info("Training completed for %s: %s", ticker, results)
        return results
    except Exception as e:
        logger.exception("Training failed for %s", ticker)
        try:
            self.retry(exc=e)
        except Exception:
            return {"ticker": ticker, "status": "error", "error": str(e)}
    finally:
        db.close()


@app.task(bind=True, max_retries=2, default_retry_delay=120, name="train_all_models")
def train_all_models(self) -> dict[str, Any]:
    """Train models for all instruments with sufficient data."""
    from src.db.connection import get_session
    from src.db.models import Instrument, Price

    db = get_session()
    try:
        instrument_ids = (
            db.query(Instrument.id, Instrument.ticker)
            .join(Price, Price.instrument_id == Instrument.id)
            .group_by(Instrument.id)
            .having(func.count(Price.id) > 60)
            .all()
        )
        logger.info("Found %d instruments for training", len(instrument_ids))
        results: dict[str, Any] = {}
        for inst_id, ticker in instrument_ids:
            try:
                result = train_model.delay(inst_id, ticker)
                results[ticker] = {"task_id": result.id, "status": "queued"}
            except Exception as e:
                logger.warning("Failed to queue training for %s: %s", ticker, e)
                results[ticker] = {"status": "error", "error": str(e)}
        return {"instruments": len(instrument_ids), "results": results}
    finally:
        db.close()


@app.task(bind=True, max_retries=2, name="generate_signals")
def generate_signals_background(self, instrument_ids: list[int] | None = None) -> dict[str, Any]:
    """Generate signals for all or specified instruments in background."""
    from src.scheduler.collectors import generate_signals

    logger.info("Generating signals in background task")
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(generate_signals(instrument_ids=instrument_ids))
            return {"status": "ok", "signals_generated": result}
        finally:
            loop.close()
    except Exception as e:
        logger.exception("Signal generation failed")
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="collect_prices")
def collect_prices_background(self) -> dict[str, Any]:
    """Collect price data in background."""
    from src.scheduler.collectors import collect_prices

    logger.info("Collecting prices in background task")
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from src.db.connection import get_session
            db = get_session()
            try:
                updated = loop.run_until_complete(collect_prices(db))
                return {"status": "ok", "updated_instruments": updated}
            finally:
                db.close()
        finally:
            loop.close()
    except Exception as e:
        logger.exception("Price collection failed")
        return {"status": "error", "error": str(e)}
