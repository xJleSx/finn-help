from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from src.analysis.ml.news_impact_features import (
    ALL_FEATURE_COLS,
    build_training_data,
    extract_features,
)
from src.config import settings
from src.model_registry import load_model as load_from_registry
from src.model_registry import save_model

logger = logging.getLogger(__name__)


class NewsImpactModel:
    def __init__(self, ticker: str = ""):
        self._ticker = ticker.upper()
        self._models: dict[int, Any] = {}
        self._feature_names: list[str] = list(ALL_FEATURE_COLS)

    @property
    def _model_prefix(self) -> str:
        prefix = "news_impact"
        return f"{prefix}_{self._ticker}" if self._ticker else prefix

    def _model_name(self, horizon_days: int) -> str:
        return f"{self._model_prefix}_{horizon_days}d"

    @property
    def horizons(self) -> list[int]:
        return sorted(int(h) for h in settings.ml_impact_horizons.split(","))

    def _create_model(self) -> Any:
        import xgboost as xgb
        return xgb.XGBRegressor(
            n_estimators=settings.ml_impact_n_estimators,
            max_depth=settings.ml_impact_max_depth,
            learning_rate=settings.ml_impact_learning_rate,
            objective="reg:squarederror",
            verbosity=0,
        )

    def train(
        self, db: Any, ticker: Optional[str] = None,
    ) -> dict[str, Any]:
        ticker = (ticker or self._ticker).upper()
        df = build_training_data(db, ticker)
        if df.empty or len(df) < settings.ml_impact_min_train_samples:
            logger.warning("Not enough samples for %s: %d", ticker, len(df))
            return {"ticker": ticker, "trained": False, "samples": len(df)}

        results: dict[str, Any] = {"ticker": ticker, "trained": True, "horizons": {}}
        for h in self.horizons:
            target = f"return_{h}d"
            if target not in df.columns:
                continue
            clean = df[self._feature_names + [target]].dropna()
            if len(clean) < settings.ml_impact_min_train_samples:
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
            direction_acc = float(np.mean((np.sign(preds) == np.sign(y_val)) | (np.abs(y_val) < 0.001)))

            self._models[h] = model
            metrics = {"rmse": round(rmse, 4), "mae": round(mae, 4), "direction_accuracy": round(direction_acc, 4)}

            fi = self._feature_importance(model)
            if fi:
                metrics["top_features"] = fi[:5]

            save_model(model, self._model_name(h), metrics=metrics)
            logger.info(
                "%s %dd — RMSE=%.4f MAE=%.4f DirAcc=%.2f (n=%d)",
                ticker, h, rmse, mae, direction_acc, len(y_val),
            )
            results["horizons"][h] = metrics

        return results

    def predict(
        self, db: Any, news_article: Any, horizon_days: int = 1,
    ) -> dict[str, Any]:
        model = self._models.get(horizon_days)
        if model is None:
            try:
                model = load_from_registry(self._model_name(horizon_days))
                self._models[horizon_days] = model
            except (ValueError, FileNotFoundError):
                return {"predicted_return": 0.0, "confidence": 0.0, "model_loaded": False}

        features = extract_features(db, news_article)
        vec = np.array([features.get(c, 0.0) for c in self._feature_names], dtype=np.float32).reshape(1, -1)

        pred = float(model.predict(vec)[0])
        confidence = min(1.0, abs(pred) * 10.0)
        return {"predicted_return": round(pred, 4), "confidence": round(confidence, 4), "model_loaded": True}

    def evaluate(
        self, db: Any, ticker: Optional[str] = None,
    ) -> dict[str, Any]:
        ticker = (ticker or self._ticker).upper()
        df = build_training_data(db, ticker)
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

            target = f"return_{h}d"
            clean = df[self._feature_names + [target]].dropna()
            if clean.empty:
                continue

            x = clean[self._feature_names].values.astype(np.float32)
            y = clean[target].values.astype(np.float32)
            preds = model.predict(x)
            rmse = float(np.sqrt(np.mean((preds - y) ** 2)))
            mae = float(np.mean(np.abs(preds - y)))
            direction_acc = float(np.mean((np.sign(preds) == np.sign(y)) | (np.abs(y) < 0.001)))

            results[f"{h}d"] = {
                "rmse": round(rmse, 4),
                "mae": round(mae, 4),
                "direction_accuracy": round(direction_acc, 4),
                "samples": len(y),
            }
        return results

    def _feature_importance(self, model: Any) -> list[dict[str, Any]]:
        try:
            scores = model.feature_importances_
            indices = np.argsort(scores)[-10:][::-1]
            return [
                {"feature": self._feature_names[i], "importance": round(float(scores[i]), 4)}
                for i in indices
            ]
        except Exception:
            return []

    def load(self, horizon_days: int) -> Any:
        model = load_from_registry(self._model_name(horizon_days))
        self._models[horizon_days] = model
        return model
