import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.brokers.tbank import TBankClient
from src.config import personal, settings
from src.db.connection import get_session
from src.db.models import Instrument, Price

logger = logging.getLogger(__name__)


async def update_candles_tbank(figi: str, ticker: str, interval: str = "5min", days: int = 5) -> int:
    if not settings.tinkoff_token:
        logger.warning("TINKOFF_TOKEN not set, skipping T-Invest candles")
        return 0

    use_sandbox = settings.tinkoff_sandbox
    new_count = 0
    async with TBankClient(use_sandbox=use_sandbox) as client:
        candles = await client.get_candles(figi=figi, interval=interval, days=days)

    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            logger.warning("Instrument %s not found in local DB", ticker)
            return 0

        for c in candles:
            d = c["time"]
            if isinstance(d, str):
                d = datetime.fromisoformat(d).date()
            exists = db.query(Price).filter_by(instrument_id=inst.id, date=d).first()
            if not exists:
                p = Price(
                    instrument_id=inst.id,
                    date=d,
                    open=c["open"],
                    high=c["high"],
                    low=c["low"],
                    close=c["close"],
                    volume=c["volume"],
                )
                db.add(p)
                new_count += 1
        db.commit()
        logger.info("Added %d candles for %s (%s)", new_count, ticker, interval)
    finally:
        db.close()
    return new_count


async def update_all_favorites(interval: str = "5min", days: int = 5) -> dict:
    stats: dict[str, int] = {}
    if not settings.tinkoff_token:
        return stats

    tickers = personal.get("favorite_tickers", ["SBER", "LKOH", "GAZP", "YNDX", "TATN"])

    # get figi mapping from instruments table
    db = get_session()
    try:
        figi_map: dict[str, str] = {}
        for t in tickers:
            inst = db.query(Instrument).filter_by(ticker=t).first()
            if inst and hasattr(inst, "figi") and inst.figi:
                figi_map[t] = inst.figi
    finally:
        db.close()

    if not figi_map:
        logger.warning("No FIGI mappings found. Run MOEX collector first.")
        return stats

    for ticker, figi in figi_map.items():
        try:
            n = await update_candles_tbank(figi=figi, ticker=ticker, interval=interval, days=days)
            stats[ticker] = n
        except Exception as e:
            logger.warning("Failed to update %s: %s", ticker, e)
            stats[ticker] = -1

    return stats
