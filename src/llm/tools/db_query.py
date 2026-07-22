from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from src.db.connection import get_session
from src.db.models import Instrument, Price

logger = logging.getLogger(__name__)


def query_prices(ticker: str, days: int = 252) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=days)
    db = get_session()
    rows = db.query(Price).join(Instrument).filter(Instrument.ticker == ticker.upper(), Price.date >= start, Price.date <= end).order_by(Price.date).all()
    db.close()
    return [{"date": r.date.isoformat(), "close": r.close, "volume": r.volume} for r in rows if r.close]


def query_instruments(ticker: str | None = None) -> list[dict[str, Any]]:
    db = get_session()
    q = db.query(Instrument)
    if ticker:
        q = q.filter(Instrument.ticker == ticker.upper())
    rows = q.all()
    db.close()
    return [
        {
            "ticker": r.ticker,
            "name": r.short_name or r.full_name or r.ticker,
            "instrument_type": r.instrument_type,
            "sector": r.sector,
        }
        for r in rows
    ]


def query_sector_performance(sector: str, days: int = 252) -> list[dict[str, Any]]:
    db = get_session()
    tickers = [r.ticker for r in db.query(Instrument).filter(Instrument.sector == sector).all()]
    end = date.today()
    start = end - timedelta(days=days)
    result: list[dict[str, Any]] = []
    for t in tickers[:20]:
        rows = db.query(Price).join(Instrument).filter(Instrument.ticker == t, Price.date >= start, Price.date <= end).order_by(Price.date).all()
        closes = [r.close for r in rows if r.close]
        if len(closes) >= 2:
            ret = (closes[-1] / closes[0]) - 1
            result.append({"ticker": t, "return": round(ret, 4), "start_date": start.isoformat(), "end_date": end.isoformat()})
    db.close()
    return result


AVAILABLE_TOOLS: dict[str, dict[str, Any]] = {
    "query_prices": {
        "description": "Get historical prices for a ticker",
        "parameters": {"ticker": "string (required)", "days": "int (optional, default 252)"},
    },
    "query_instruments": {
        "description": "Look up instrument metadata by ticker or list all",
        "parameters": {"ticker": "string (optional)"},
    },
    "query_sector_performance": {
        "description": "Get performance of all tickers in a sector",
        "parameters": {"sector": "string (required)", "days": "int (optional, default 252)"},
    },
}
