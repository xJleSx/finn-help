from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.analysis.ml._base import BaseRegressor, log_feature_importance
from src.config import settings
from src.db.models import Instrument, News, NewsInstrument
from src.model_registry import load_model as load_from_registry

logger = logging.getLogger(__name__)


class SentimentEvolutionModel(BaseRegressor):
    def __init__(self, ticker: str = ""):
        super().__init__(ticker)
        self._models: dict[int, Any] = {}
        self._feature_names = [
            "sentiment_mean", "sentiment_std", "article_count",
            "positive_ratio", "negative_ratio",
            "sentiment_ma_3d", "sentiment_ma_7d", "sentiment_std_5d",
            "sentiment_change_1d", "sentiment_change_3d", "sentiment_change_7d",
        ]

    @property
    def _model_prefix(self) -> str:
        return "sentiment_evolution"

    def _model_name(self, horizon_days: int) -> str:
        return f"{self.model_name}_{horizon_days}d"

    @property
    def horizons(self) -> list[int]:
        return sorted(int(h) for h in settings.ml_sentiment_horizons.split(","))

    def _create_model(self) -> Any:
        import xgboost as xgb
        return xgb.XGBRegressor(
            n_estimators=settings.ml_sentiment_n_estimators,
            max_depth=settings.ml_sentiment_max_depth,
            learning_rate=settings.ml_sentiment_learning_rate,
            objective="reg:squarederror",
            verbosity=0,
        )

    def _build_training_data(self, db: Any, ticker: str) -> pd.DataFrame:
        instrument = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not instrument:
            return pd.DataFrame()

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.ml_sentiment_days_back)
        articles = (
            db.query(News)
            .join(NewsInstrument, NewsInstrument.news_id == News.id)
            .filter(
                NewsInstrument.instrument_id == instrument.id,
                News.is_relevant,
                News.published_at >= cutoff,
                News.sentiment_score.isnot(None),
            )
            .order_by(News.published_at.asc())
            .all()
        )
        if not articles:
            return pd.DataFrame()

        rows = []
        for a in articles:
            rows.append({
                "date": (a.published_at or a.created_at).date(),
                "sentiment_score": float(a.sentiment_score or 0.0),
                "sentiment": a.sentiment or "",
            })

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        daily = df.groupby("date").agg(
            sentiment_mean=("sentiment_score", "mean"),
            sentiment_std=("sentiment_score", "std"),
            article_count=("sentiment_score", "count"),
            positive_ratio=("sentiment", lambda x: float((x == "positive").sum()) / max(len(x), 1)),
            negative_ratio=("sentiment", lambda x: float((x == "negative").sum()) / max(len(x), 1)),
        ).reset_index()
        daily = daily.sort_values("date").reset_index(drop=True)
        daily["sentiment_std"] = daily["sentiment_std"].fillna(0.0)

        daily["sentiment_ma_3d"] = daily["sentiment_mean"].rolling(3, min_periods=1).mean()
        daily["sentiment_ma_7d"] = daily["sentiment_mean"].rolling(7, min_periods=1).mean()
        daily["sentiment_std_5d"] = daily["sentiment_mean"].rolling(5, min_periods=1).std().fillna(0.0)
        daily["sentiment_change_1d"] = daily["sentiment_mean"].diff(1).fillna(0.0)
        daily["sentiment_change_3d"] = daily["sentiment_mean"].diff(3).fillna(0.0)
        daily["sentiment_change_7d"] = daily["sentiment_mean"].diff(7).fillna(0.0)

        for h in self.horizons:
            daily[f"target_{h}d"] = daily["sentiment_mean"].shift(-h)

        return daily

    def train(
        self, db: Any, ticker: Optional[str] = None,
    ) -> dict[str, Any]:
        ticker = (ticker or self._ticker).upper()
        df = self._build_training_data(db, ticker)
        if df.empty or len(df) < settings.ml_sentiment_min_train_samples:
            logger.warning("Not enough daily samples for %s: %d", ticker, len(df))
            return {"ticker": ticker, "trained": False, "samples": len(df)}

        results: dict[str, Any] = {"ticker": ticker, "trained": True, "horizons": {}}
        for h in self.horizons:
            target = f"target_{h}d"
            if target not in df.columns:
                continue
            clean = df[self._feature_names + [target]].dropna()
            if len(clean) < settings.ml_sentiment_min_train_samples:
                continue

            x = clean[self._feature_names].values.astype(np.float32)
            y = clean[target].values.astype(np.float32)

            split = int(len(x) * 0.8)
            x_train, x_val = x[:split], x[split:]
            y_train, y_val = y[:split], y[split:]

            model = self._create_model()
            model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)

            preds = model.predict(x_val)
            rmse = float(np.sqrt(np.mean((preds - y_val) ** 2)))
            mae = float(np.mean(np.abs(preds - y_val)))

            current_sentiment = clean["sentiment_mean"].values[split:]
            pred_dir = preds - current_sentiment
            actual_dir = y_val - current_sentiment
            direction_acc = float(np.mean((np.sign(pred_dir) == np.sign(actual_dir)) | (np.abs(actual_dir) < 0.001)))

            self._models[h] = model
            metrics = {"rmse": round(rmse, 4), "mae": round(mae, 4), "direction_accuracy": round(direction_acc, 4)}

            fi = log_feature_importance(model, self._feature_names)
            if fi:
                metrics["top_features"] = fi[:5]

            from src.model_registry import save_model
            save_model(model, self._model_name(h), metrics=metrics)
            logger.info(
                "%s %dd — RMSE=%.4f MAE=%.4f DirAcc=%.2f (n=%d)",
                ticker, h, rmse, mae, direction_acc, len(y_val),
            )
            results["horizons"][h] = metrics

        return results

    def predict(
        self, db: Any, news_article: Any, horizon_days: int = 3,
    ) -> dict[str, Any]:
        model = self._models.get(horizon_days)
        if model is None:
            try:
                model = load_from_registry(self._model_name(horizon_days))
                self._models[horizon_days] = model
            except (ValueError, FileNotFoundError):
                return {"predicted_sentiment": 0.0, "direction": "stable", "confidence": 0.0}

        linked = (
            db.query(NewsInstrument)
            .filter(NewsInstrument.news_id == news_article.id)
            .first()
        )
        if not linked:
            return {"predicted_sentiment": 0.0, "direction": "stable", "confidence": 0.0}

        instrument = db.query(Instrument).filter_by(id=linked.instrument_id).first()
        if not instrument:
            return {"predicted_sentiment": 0.0, "direction": "stable", "confidence": 0.0}

        df = self._build_training_data(db, instrument.ticker)
        if df.empty:
            return {"predicted_sentiment": 0.0, "direction": "stable", "confidence": 0.0}

        latest = df.iloc[-1:]
        vec = np.array([latest[c].values[0] for c in self._feature_names], dtype=np.float32).reshape(1, -1)

        pred = float(model.predict(vec)[0])
        current_sentiment = float(latest["sentiment_mean"].values[0])
        delta = pred - current_sentiment

        if delta > 0.05:
            direction = "improving"
            confidence = min(1.0, abs(delta) * 5.0)
        elif delta < -0.05:
            direction = "deteriorating"
            confidence = min(1.0, abs(delta) * 5.0)
        else:
            direction = "stable"
            confidence = 0.5

        return {
            "predicted_sentiment": round(pred, 4),
            "direction": direction,
            "confidence": round(confidence, 4),
        }

    def evaluate(
        self, db: Any, ticker: Optional[str] = None,
    ) -> dict[str, Any]:
        ticker = (ticker or self._ticker).upper()
        df = self._build_training_data(db, ticker)
        if df.empty:
            return {}

        results: dict[str, Any] = {}
        for h in self.horizons:
            model = self._models.get(h)
            if model is None:
                try:
                    model = load_from_registry(self._model_name(h))
                except (ValueError, FileNotFoundError):
                    continue
                self._models[h] = model

            target = f"target_{h}d"
            clean = df[self._feature_names + [target]].dropna()
            if clean.empty:
                continue

            x = clean[self._feature_names].values.astype(np.float32)
            y = clean[target].values.astype(np.float32)
            preds = model.predict(x)

            mae = float(np.mean(np.abs(preds - y)))

            current = clean["sentiment_mean"].values
            pred_dir = preds - current
            actual_dir = y - current
            direction_acc = float(np.mean((np.sign(pred_dir) == np.sign(actual_dir)) | (np.abs(actual_dir) < 0.001)))

            results[f"{h}d"] = {
                "mae": round(mae, 4),
                "direction_accuracy": round(direction_acc, 4),
                "samples": len(y),
            }
        return results

    def _feature_importance(self, model: Any) -> list[dict[str, Any]]:
        return log_feature_importance(model, self._feature_names)

    def load(self, horizon_days: int) -> Any:
        model = load_from_registry(self._model_name(horizon_days))
        self._models[horizon_days] = model
        return model
