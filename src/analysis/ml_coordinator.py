from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np
import pandas as pd
from sqlalchemy import select

from src.analysis.events import EventFeatureBuilder, event_features
from src.db.models import Indicator, Instrument, MarketEvent, Price

logger = logging.getLogger(__name__)


class MLCoordinator:
    def __init__(self) -> None:
        self._prophet_cache: dict[str, Any] = {}
        self._ensemble_cache: dict[str, Any] = {}

    def get_prophet(self, ticker: str = "") -> Any:
        if ticker not in self._prophet_cache:
            from src.analysis.ml.prophet_model import ProphetPredictor

            self._prophet_cache[ticker] = ProphetPredictor(ticker=ticker)
        return self._prophet_cache[ticker]

    def get_ensemble(self, ticker: str = "") -> Any:
        if ticker not in self._ensemble_cache:
            from src.analysis.ml.ensemble import EnsemblePredictor

            self._ensemble_cache[ticker] = EnsemblePredictor(ticker=ticker)
        return self._ensemble_cache[ticker]

    def compute_ml(
        self,
        df: pd.DataFrame,
        ind_df: pd.DataFrame,
        ticker: str = "",
        events: list[MarketEvent] | None = None,
        event_builder: EventFeatureBuilder | None = None,
    ) -> dict[str, Any] | None:
        if len(df) < 60:
            return None
        try:
            anomaly_mask = None
            if events:
                builder = event_builder or event_features
                ef = builder.build_features(events, ind_df["date"])
                ind_df = ind_df.merge(ef, on="date", how="left")
                for c in ["event_count_30d", "event_severity_30d", "sanctions_30d", "days_since_major_event"]:
                    if c in ind_df.columns:
                        ind_df[c] = ind_df[c].fillna(0)
                if "is_anomaly" in ind_df.columns:
                    anomaly_mask = ind_df["is_anomaly"].fillna(False).to_numpy(dtype=bool)
                    ind_df = ind_df.drop(columns=["is_anomaly"])

            pr = self.get_prophet(ticker).predict(df)
            ensemble = self.get_ensemble(ticker).predict(ind_df, anomaly_mask=anomaly_mask)
            ml = pr
            ml["ml_confidence"] = max(pr.get("confidence", 0), ensemble.get("confidence", 0))
            ml["xgb_action"] = ensemble.get("xgb_action", "NEUTRAL")
            ml["ensemble"] = {
                "lgb_action": ensemble.get("lgb_action", "NEUTRAL"),
                "cat_action": ensemble.get("cat_action", "NEUTRAL"),
                "model_votes": ensemble.get("model_votes", {}),
            }
            return cast(dict[str, Any], ml)
        except Exception:
            logger.warning("ML prediction failed", exc_info=True)
            return None

    def price_df(self, prices: list[Any]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"date": p.date, "open": p.open, "high": p.high, "low": p.low, "close": p.close, "volume": p.volume}
                for p in prices
            ]
        )

    def indicator_df(self, rows: list[Any]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": r.date,
                    "rsi": r.rsi,
                    "macd_line": r.macd_line,
                    "macd_signal": r.macd_signal,
                    "macd_hist": r.macd_hist,
                    "sma_20": r.sma_20,
                    "sma_50": r.sma_50,
                    "sma_200": r.sma_200,
                    "bb_upper": r.bb_upper,
                    "bb_lower": r.bb_lower,
                    "bb_mid": r.bb_mid,
                    "volume_sma_20": r.volume_sma_20,
                    "atr": r.atr,
                }
                for r in rows
            ]
        )

    def dividend_df(self, divs: list[Any]) -> pd.DataFrame:
        return pd.DataFrame([{"date": d.date, "amount": d.amount} for d in divs])

    def train_models(
        self,
        db: Any,
        ticker: str | None = None,
        event_builder: EventFeatureBuilder | None = None,
    ) -> dict[str, bool]:
        from sqlalchemy import select as sa_select

        q = sa_select(Instrument)
        if ticker:
            q = q.where(Instrument.ticker == ticker.upper())
        result = db.execute(q)
        instruments = result.scalars().all()

        builder = event_builder or event_features
        all_results: dict[str, bool] = {}
        for inst in instruments:
            sym = str(inst.ticker or "")
            prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
            if len(prices) < 60:
                logger.info("Skipping %s: only %d prices", sym, len(prices))
                continue
            df = self.price_df(prices)

            ind_rows = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date).all()
            if len(ind_rows) < 2:
                logger.info("Skipping %s: no indicators", sym)
                continue
            ind_df = self.indicator_df(ind_rows)
            ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

            all_events = builder.load_all_events_sync(db)
            anomaly_mask = None
            train_df = ind_df.copy()
            if all_events:
                ef = builder.build_features(all_events, ind_df["date"])
                train_df = ind_df.merge(ef, on="date", how="left")
                for c in ["event_count_30d", "event_severity_30d", "sanctions_30d", "days_since_major_event"]:
                    if c in train_df.columns:
                        train_df[c] = train_df[c].fillna(0)
                if "is_anomaly" in train_df.columns:
                    anomaly_mask = train_df["is_anomaly"].fillna(False).to_numpy(dtype=bool)
                    train_df = train_df.drop(columns=["is_anomaly"])

            ensemble = self.get_ensemble(sym)
            ensemble_ok = ensemble.train_all(train_df, anomaly_mask=anomaly_mask)

            prophet = self.get_prophet(sym)
            prophet_ok = prophet.train(df)

            all_results[sym] = all(ensemble_ok.values()) and prophet_ok
            logger.info(
                "Model training for %s: ensemble=%s prophet=%s",
                sym,
                "OK" if all(ensemble_ok.values()) else "partial",
                "OK" if prophet_ok else "FAIL",
            )
        return all_results


ml_coordinator = MLCoordinator()
