import logging

import pandas as pd
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

        price_dict: dict[str, pd.Series] = {}
        for inst in instruments:
            rows = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.asc()).all()
            if len(rows) < 20:
                continue
            closes = pd.Series(
                [r.close for r in rows],
                index=pd.DatetimeIndex([r.date for r in rows]),
                name=inst.ticker,
            )
            price_dict[inst.ticker] = closes

        if len(price_dict) < 2:
            return None

        df = pd.DataFrame(price_dict)
        returns = df.pct_change().dropna()
        if returns.shape[1] < 2 or returns.shape[0] < 10:
            return None

        return returns.corr(method="pearson")


correlation = CorrelationAnalyzer()
