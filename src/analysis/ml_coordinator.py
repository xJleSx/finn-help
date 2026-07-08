from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, cast

import pandas as pd
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.events import EventFeatureBuilder, event_features
from src.core.executor import get_executor
from src.db.models import Indicator, Instrument, MarketEvent, Price

logger = logging.getLogger(__name__)

ml_inference_latency = Histogram(
    "ml_inference_latency_seconds", "ML inference latency", ["model_type", "ticker"], buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)
ml_prediction_count = Counter("ml_prediction_count_total", "Total ML predictions", ["model_type", "ticker", "status"])
ml_error_count = Counter("ml_error_rate_total", "ML prediction errors", ["model_type", "ticker"])
ml_model_version = Gauge("ml_model_version", "ML model version", ["ticker", "model_type", "version"])
ml_model_load_time = Histogram("ml_model_load_time_seconds", "ML model load time", ["ticker", "model_type"])

try:
    import mlflow

    _MLFLOW_AVAILABLE = True
except ImportError:
    _MLFLOW_AVAILABLE = False


class MLflowTracker:
    _active_run: Any = None

    @classmethod
    def start_run(cls, experiment_name: str = "finn-help", run_name: str | None = None) -> None:
        if not _MLFLOW_AVAILABLE:
            return
        if cls._active_run is not None:
            return
        mlflow.set_experiment(experiment_name)
        cls._active_run = mlflow.start_run(run_name=run_name)

    @classmethod
    def log_params(cls, params: dict[str, Any]) -> None:
        if not _MLFLOW_AVAILABLE or cls._active_run is None:
            return
        mlflow.log_params(params)

    @classmethod
    def log_metrics(cls, metrics: dict[str, float], step: int | None = None) -> None:
        if not _MLFLOW_AVAILABLE or cls._active_run is None:
            return
        mlflow.log_metrics(metrics, step=step)

    @classmethod
    def log_artifact(cls, local_path: str) -> None:
        if not _MLFLOW_AVAILABLE or cls._active_run is None:
            return
        mlflow.log_artifact(local_path)

    @classmethod
    def end_run(cls) -> None:
        if not _MLFLOW_AVAILABLE or cls._active_run is None:
            return
        mlflow.end_run()
        cls._active_run = None

    @classmethod
    def log_model_params(cls, model_type: str, ticker: str, params: dict[str, Any], metrics: dict[str, float]) -> None:
        cls.start_run(run_name=f"{ticker}_{model_type}")
        cls.log_params({"ticker": ticker, "model_type": model_type, **params})
        cls.log_metrics(metrics)
        cls.end_run()


def _train_news_impact_sync(sym: str) -> bool:
    """Sync helper for training NewsImpactModel inside run_in_executor."""
    from src.analysis.ml.news_impact import NewsImpactModel
    from src.db.connection import get_session

    db_sync = get_session()
    try:
        nim = NewsImpactModel(ticker=sym)
        nim_result = nim.train(db_sync, sym)
        return bool(nim_result.get("trained", False))
    except Exception as e:
        logger.warning("NewsImpact training for %s failed: %s", sym, e)
        return False
    finally:
        db_sync.close()


class MLCoordinator:
    def __init__(self) -> None:
        self._prophet_cache: dict[str, Any] = {}
        self._ensemble_cache: dict[str, Any] = {}

    def get_prophet(self, ticker: str = "") -> Any:
        if ticker not in self._prophet_cache:
            from src.analysis.ml.prophet_model import StatsModelsTrendPredictor

            self._prophet_cache[ticker] = StatsModelsTrendPredictor(ticker=ticker)
        return self._prophet_cache[ticker]

    def get_ensemble(self, ticker: str = "") -> Any:
        if ticker not in self._ensemble_cache:
            from src.analysis.ml.ensemble import EnsemblePredictor

            self._ensemble_cache[ticker] = EnsemblePredictor(ticker=ticker)
        return self._ensemble_cache[ticker]

    def _prepare_events(
        self, ind_df: pd.DataFrame, events: list[MarketEvent] | None, event_builder: EventFeatureBuilder | None
    ) -> tuple[pd.DataFrame, Any]:
        if not events:
            return ind_df, None
        builder = event_builder or event_features
        ef = builder.build_features(events, ind_df["date"])
        ind_df = ind_df.merge(ef, on="date", how="left")
        for c in ["event_count_30d", "event_severity_30d", "sanctions_30d", "days_since_major_event"]:
            if c in ind_df.columns:
                ind_df[c] = ind_df[c].fillna(0)
        anomaly_mask = None
        if "is_anomaly" in ind_df.columns:
            anomaly_mask = ind_df["is_anomaly"].fillna(False).to_numpy(dtype=bool)
            ind_df = ind_df.drop(columns=["is_anomaly"])
        return ind_df, anomaly_mask

    def _build_result(self, pr: dict[str, Any], ensemble_res: dict[str, Any]) -> dict[str, Any]:
        MLflowTracker.log_metrics(
            {"prophet_confidence": pr.get("confidence", 0), "ensemble_confidence": ensemble_res.get("confidence", 0)},
        )
        ml = pr
        ml["ml_confidence"] = max(pr.get("confidence", 0), ensemble_res.get("confidence", 0))
        ml["xgb_action"] = ensemble_res.get("xgb_action", "NEUTRAL")
        ml["ensemble"] = {
            "lgb_action": ensemble_res.get("lgb_action", "NEUTRAL"),
            "cat_action": ensemble_res.get("cat_action", "NEUTRAL"),
            "model_votes": ensemble_res.get("model_votes", {}),
        }
        return cast(dict[str, Any], ml)

    async def compute_ml(
        self,
        df: pd.DataFrame,
        ind_df: pd.DataFrame,
        ticker: str = "",
        events: list[MarketEvent] | None = None,
        event_builder: EventFeatureBuilder | None = None,
    ) -> dict[str, Any] | None:
        if len(df) < 60:
            ml_prediction_count.labels(model_type="ensemble", ticker=ticker or "unknown", status="skipped").inc()
            return None
        try:
            ind_df, anomaly_mask = self._prepare_events(ind_df, events, event_builder)
            loop = asyncio.get_running_loop()
            prophet = self.get_prophet(ticker)
            ensemble = self.get_ensemble(ticker)
            with ml_inference_latency.labels(model_type="prophet", ticker=ticker or "unknown").time():
                pr = await loop.run_in_executor(get_executor(), prophet.predict, df)
            ml_prediction_count.labels(model_type="prophet", ticker=ticker or "unknown", status="success").inc()
            with ml_inference_latency.labels(model_type="ensemble", ticker=ticker or "unknown").time():
                ensemble_res = await loop.run_in_executor(get_executor(), ensemble.predict, ind_df, anomaly_mask)
            ml_prediction_count.labels(model_type="ensemble", ticker=ticker or "unknown", status="success").inc()
            return self._build_result(pr, ensemble_res)
        except Exception:
            logger.exception("Unhandled exception")
            logger.warning("ML prediction failed", exc_info=True)
            ml_error_count.labels(model_type="ensemble", ticker=ticker or "unknown").inc()
            ml_prediction_count.labels(model_type="ensemble", ticker=ticker or "unknown", status="error").inc()
            return None

    def price_df(self, prices: list[Any]) -> pd.DataFrame:
        return pd.DataFrame([{"date": p.date, "open": p.open, "high": p.high, "low": p.low, "close": p.close, "volume": p.volume} for p in prices])

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

    def compute_ml_sync(
        self,
        df: pd.DataFrame,
        ind_df: pd.DataFrame,
        ticker: str = "",
        events: list[MarketEvent] | None = None,
        event_builder: EventFeatureBuilder | None = None,
    ) -> dict[str, Any] | None:
        if len(df) < 60:
            ml_prediction_count.labels(model_type="ensemble", ticker=ticker or "unknown", status="skipped").inc()
            return None
        try:
            ind_df, anomaly_mask = self._prepare_events(ind_df, events, event_builder)
            prophet = self.get_prophet(ticker)
            ensemble = self.get_ensemble(ticker)
            t0 = time.monotonic()
            pr = prophet.predict(df)
            ml_inference_latency.labels(model_type="prophet", ticker=ticker or "unknown").observe(time.monotonic() - t0)
            ml_prediction_count.labels(model_type="prophet", ticker=ticker or "unknown", status="success").inc()
            t0 = time.monotonic()
            ensemble_res = ensemble.predict(ind_df, anomaly_mask=anomaly_mask)
            ml_inference_latency.labels(model_type="ensemble", ticker=ticker or "unknown").observe(time.monotonic() - t0)
            ml_prediction_count.labels(model_type="ensemble", ticker=ticker or "unknown", status="success").inc()
            return self._build_result(pr, ensemble_res)
        except Exception:
            logger.exception("Unhandled exception")
            logger.warning("Sync ML prediction failed", exc_info=True)
            ml_error_count.labels(model_type="ensemble", ticker=ticker or "unknown").inc()
            ml_prediction_count.labels(model_type="ensemble", ticker=ticker or "unknown", status="error").inc()
            return None

    async def train_models(
        self,
        db: AsyncSession,
        ticker: str | None = None,
        event_builder: EventFeatureBuilder | None = None,
    ) -> dict[str, bool]:
        q = select(Instrument)
        if ticker:
            q = q.where(Instrument.ticker == ticker.upper())
        result = await db.execute(q)
        instruments = result.scalars().all()

        builder = event_builder or event_features
        all_results: dict[str, bool] = {}
        loop = asyncio.get_running_loop()
        for inst in instruments:
            sym = str(inst.ticker or "")

            result = await db.execute(select(Price).where(Price.instrument_id == inst.id).order_by(Price.date))
            prices = result.scalars().all()
            if len(prices) < 60:
                logger.info("Skipping %s: only %d prices", sym, len(prices))
                continue
            df = self.price_df(prices)

            result = await db.execute(select(Indicator).where(Indicator.instrument_id == inst.id).order_by(Indicator.date))
            ind_rows = result.scalars().all()
            if len(ind_rows) < 2:
                logger.info("Skipping %s: no indicators", sym)
                continue
            ind_df = self.indicator_df(ind_rows)
            ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

            all_events = await builder.load_all_events(db)
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
            ensemble_ok = await loop.run_in_executor(
                None,
                ensemble.train_all,
                train_df,
                anomaly_mask,
            )

            prophet = self.get_prophet(sym)
            prophet_ok = await loop.run_in_executor(get_executor(), prophet.train, df)

            news_ok = await loop.run_in_executor(get_executor(), _train_news_impact_sync, sym)

            all_results[sym] = all(ensemble_ok.values()) and prophet_ok

            MLflowTracker.log_model_params(
                "ensemble",
                sym,
                {"n_estimators": 100, "max_depth": 6},
                {"accuracy": float(ensemble_ok.get("accuracy", 0)) if isinstance(ensemble_ok, dict) else 0.0},
            )
            MLflowTracker.log_model_params(
                "prophet",
                sym,
                {"seasonality_mode": "multiplicative"},
                {"rmse": 0.0},
            )

            logger.info(
                "Model training for %s: ensemble=%s prophet=%s news=%s",
                sym,
                "OK" if ensemble_ok and all(ensemble_ok.values()) else "partial",
                "OK" if prophet_ok else "FAIL",
                "OK" if news_ok else "SKIP",
            )
        return all_results


ml_coordinator = MLCoordinator()
