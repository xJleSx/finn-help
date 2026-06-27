from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.db.models import Instrument, Price

logger = logging.getLogger(__name__)


class CorrelationAnalyzer:
    THRESHOLD = 0.7

    def diversification_penalty(self, ticker: str, existing_tickers: list[str], db: Session) -> float:
        if not existing_tickers:
            return 0.0

        all_tickers = [ticker] + [t for t in existing_tickers if t != ticker]
        matrix = self._load_correlation_matrix(all_tickers, db)
        if matrix is None or ticker not in matrix.index:
            return 0.0

        row = matrix.loc[ticker]
        max_corr = 0.0
        for et in existing_tickers:
            if et in row.index:
                corr = abs(row[et])
                if corr > max_corr:
                    max_corr = corr

        if max_corr > self.THRESHOLD:
            penalty = (max_corr - self.THRESHOLD) * 2.0
            logger.debug("Correlation penalty %.2f for %s vs existing", penalty, ticker)
            return round(penalty, 2)
        return 0.0

    def _load_correlation_matrix(self, tickers: list[str], db: Session) -> pd.DataFrame | None:
        instruments = db.query(Instrument).filter(Instrument.ticker.in_(tickers)).all()
        if len(instruments) < 2:
            return None

        inst_ids = [inst.id for inst in instruments]
        all_prices = (
            db.query(Price.instrument_id, Price.date, Price.close)
            .filter(Price.instrument_id.in_(inst_ids))
            .order_by(Price.date.asc())
            .all()
        )

        id_to_ticker = {int(inst.id): str(inst.ticker) for inst in instruments}

        price_dict: dict[str, pd.Series] = {}
        temp: dict[int, list[Any]] = {}
        for pid, d, close in all_prices:
            if close is None:
                continue
            temp.setdefault(int(pid), []).append((d, close))

        for pid, rows in temp.items():
            ticker = id_to_ticker.get(pid)
            if not ticker or len(rows) < 20:
                continue
            dates, closes = zip(*rows)
            price_dict[ticker] = pd.Series(
                closes,
                index=pd.DatetimeIndex(dates),
                name=ticker,
            )

        if len(price_dict) < 2:
            return None

        df = pd.DataFrame(price_dict)
        returns = df.pct_change().dropna()
        if returns.shape[1] < 2 or returns.shape[0] < 10:
            return None

        return returns.corr(method="pearson")

    async def diversification_penalty_async(self, ticker: str, existing_tickers: list[str], db: AsyncSession) -> float:
        if not existing_tickers:
            return 0.0

        all_tickers = [ticker] + [t for t in existing_tickers if t != ticker]
        matrix = await self._load_correlation_matrix_async(all_tickers, db)
        if matrix is None or ticker not in matrix.index:
            return 0.0

        row = matrix.loc[ticker]
        max_corr = 0.0
        for et in existing_tickers:
            if et in row.index:
                corr = abs(row[et])
                if corr > max_corr:
                    max_corr = corr

        if max_corr > self.THRESHOLD:
            penalty = (max_corr - self.THRESHOLD) * 2.0
            logger.debug("Correlation penalty %.2f for %s vs existing", penalty, ticker)
            return round(penalty, 2)
        return 0.0

    async def _load_correlation_matrix_async(self, tickers: list[str], db: AsyncSession) -> pd.DataFrame | None:
        result = await db.execute(select(Instrument).where(Instrument.ticker.in_(tickers)))
        instruments = result.scalars().all()
        if len(instruments) < 2:
            return None

        inst_ids = [inst.id for inst in instruments]
        id_to_ticker = {int(inst.id): str(inst.ticker) for inst in instruments}

        price_result = await db.execute(
            select(Price.instrument_id, Price.date, Price.close)
            .where(Price.instrument_id.in_(inst_ids))
            .order_by(Price.date.asc())
        )
        all_prices = price_result.all()

        price_dict: dict[str, pd.Series] = {}
        temp: dict[int, list[Any]] = {}
        for row in all_prices:
            pid, d, close = row[0], row[1], row[2]
            if close is None:
                continue
            temp.setdefault(int(pid), []).append((d, close))

        for pid, rows in temp.items():
            ticker = id_to_ticker.get(pid)
            if not ticker or len(rows) < 20:
                continue
            dates, closes = zip(*rows)
            price_dict[ticker] = pd.Series(
                closes,
                index=pd.DatetimeIndex(dates),
                name=ticker,
            )

        if len(price_dict) < 2:
            return None

        df = pd.DataFrame(price_dict)
        returns = df.pct_change().dropna()
        if returns.shape[1] < 2 or returns.shape[0] < 10:
            return None

        return returns.corr(method="pearson")


correlation = CorrelationAnalyzer()
