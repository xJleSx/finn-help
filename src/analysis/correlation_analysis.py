import logging

import numpy as np
import pandas as pd

from src.db.connection import get_session
from src.db.models import Instrument, Price

logger = logging.getLogger(__name__)


def correlation_table(tickers: list[str] | None = None) -> str:
    import os

    db = get_session()
    try:
        if not tickers:
            tickers_str = os.environ.get("FAVORITE_TICKERS", "SBER,LKOH,GAZP,YNDX,TATN,NOVK,ROSN")
            tickers = [t.strip() for t in tickers_str.split(",") if t.strip()]

        instruments = db.query(Instrument).filter(Instrument.ticker.in_(tickers)).all()
        if len(instruments) < 2:
            return "Нужно минимум 2 инструмента для корреляции"

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
            price_dict[str(inst.ticker)] = closes

        if len(price_dict) < 2:
            return "Недостаточно данных для расчёта корреляции"

        df = pd.DataFrame(price_dict)
        returns = df.pct_change().dropna()
        corr = returns.corr(method="pearson")

        lines = ["📊 *Корреляция доходностей (Pearson)*\n"]
        ticker_list = list(corr.columns)
        # header
        header = "Тикер" + "".join(f" {t:>6}" for t in ticker_list)
        lines.append(f"```\n{header}")
        for t1 in ticker_list:
            row_str = f"{t1:<5}" + "".join(f" {corr.loc[t1, t2]:>6.2f}" for t2 in ticker_list)
            lines.append(row_str)
        lines.append("```")

        # highlight pairs with high correlation
        high_pairs = []
        for i, t1 in enumerate(ticker_list):
            for t2 in ticker_list[i + 1 :]:
                val = corr.loc[t1, t2]
                if abs(val) > 0.8:
                    high_pairs.append(f"  🔴 {t1} ↔ {t2}: {val:.2f}")
                elif abs(val) > 0.6:
                    high_pairs.append(f"  🟡 {t1} ↔ {t2}: {val:.2f}")

        if high_pairs:
            lines.append("\n*Высокая корреляция (>0.6):*")
            lines.extend(high_pairs)

        return "\n".join(lines)
    finally:
        db.close()
