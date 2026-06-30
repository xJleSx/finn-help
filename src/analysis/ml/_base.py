from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.analysis.ml.walk_forward import (
    baseline_accuracy,
    build_labels,
    compute_classification_metrics,
    temporal_split,
)
from src.config import settings
from src.model_registry import load_model as load_from_registry
from src.model_registry import save_model

logger = logging.getLogger(__name__)

EVENT_FEATURE_COLS = ["event_count_30d", "event_severity_30d", "sanctions_30d", "days_since_major_event"]
BASE_FEATURE_COLS = [
    "close",
    "rsi",
    "macd_hist",
    "sma_20",
    "sma_50",
    "price_sma20",
    "price_sma50",
    "sma20_sma50",
    "rsi_norm",
    "macd_signal_binary",
]


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    needed = ["rsi", "macd_hist", "sma_20", "sma_50", "close"]
    if not all(c in df.columns for c in needed):
        return pd.DataFrame()

    result = df[needed].copy()
    result["price_sma20"] = result["close"] / result["sma_20"].replace(0, np.nan)
    result["price_sma50"] = result["close"] / result["sma_50"].replace(0, np.nan)
    result["sma20_sma50"] = result["sma_20"] / result["sma_50"].replace(0, np.nan)
    result["rsi_norm"] = result["rsi"] / 100
    result["macd_signal_binary"] = (result["macd_hist"] > 0).astype(int)
    for c in EVENT_FEATURE_COLS:
        result[c] = df[c].values if c in df.columns else 0
    result = result.dropna()
    return result


def log_shap(model: Any, x_train: np.ndarray, x_val: np.ndarray, model_name: str, feature_names: list[str]) -> None:
    try:
        import shap

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(x_val)
        mean_abs = np.mean(np.abs(shap_values), axis=0)
        if len(mean_abs) > 0:
            top_k = min(5, len(mean_abs))
            top_idx = np.argsort(mean_abs)[-top_k:][::-1]
            parts = [f"{feature_names[i]}:{mean_abs[i]:.4f}" for i in top_idx]
            logger.info("%s — SHAP top features: %s", model_name, " ".join(parts))
    except Exception as e:
        logger.debug("SHAP unavailable: %s", e)


def log_feature_importance(model: Any, feature_names: list[str]) -> list[dict[str, Any]]:
    try:
        scores = model.feature_importances_
        indices = np.argsort(scores)[-10:][::-1]
        return [
            {"feature": feature_names[i], "importance": round(float(scores[i]), 4)}
            for i in indices
        ]
    except Exception:
        return []


class PersistMixin:
    _model: Any = None
    _ticker: str = ""

    @property
    @abstractmethod
    def _model_prefix(self) -> str: ...

    @property
    def model_name(self) -> str:
        return f"{self._model_prefix}_{self._ticker}" if self._ticker else self._model_prefix

    def save(self, metrics: Optional[dict[str, Any]] = None) -> str:
        if self._model is None:
            raise ValueError("No trained model to save")
        return save_model(self._model, self.model_name, metrics=metrics)

    def load(self, version: Optional[str] = None) -> Any:
        self._model = self._post_load(load_from_registry(self.model_name, version=version))
        return self._model

    def _post_load(self, model: Any) -> Any:
        return model


class BaseMLClassifier(PersistMixin, ABC):
    def __init__(self, ticker: str = ""):
        self._model: Any = None
        self._ticker = ticker

    @property
    def _common_model_params(self) -> dict[str, Any]:
        return {
            "n_estimators": settings.ml_n_estimators,
            "max_depth": settings.ml_max_depth,
            "learning_rate": settings.ml_learning_rate,
        }

    @abstractmethod
    def _create_model(self) -> Any: ...

    def train(self, df: pd.DataFrame, anomaly_mask: np.ndarray | None = None) -> bool:
        features = prepare_features(df)
        if features.empty or len(features) < settings.ml_min_train_rows:
            return False
        result = self._train_on_the_fly(df, features, anomaly_mask=anomaly_mask)
        if result is None:
            return False
        model, val_metrics = result
        self._model = model
        save_metrics: dict[str, Any] = {"rows": len(features), "ticker": self._ticker}
        if val_metrics:
            save_metrics["val_accuracy"] = val_metrics.get("accuracy", 0)
            save_metrics["val_precision"] = val_metrics.get("precision", 0)
            save_metrics["val_recall"] = val_metrics.get("recall", 0)
            save_metrics["val_f1"] = val_metrics.get("f1", 0)
        self.save(metrics=save_metrics)
        return True

    def predict(self, df: pd.DataFrame, anomaly_mask: np.ndarray | None = None) -> dict[str, Any]:
        if df.empty or len(df) < settings.ml_min_predict_rows:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        features = prepare_features(df)
        if features.empty or len(features) < settings.ml_min_train_rows:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        model = self._model
        if model is None:
            try:
                model = self.load()
            except (ValueError, FileNotFoundError):
                pass

        if model is None:
            result = self._train_on_the_fly(df, features, anomaly_mask=anomaly_mask)
            if result is not None:
                model, _ = result
                if model is not None:
                    self._model = model
                    self.save(metrics={"rows": len(features), "ticker": self._ticker})

        if model is None:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        proba = float(self._predict_latest(features))

        threshold_high = settings.ml_action_threshold
        threshold_low = 1.0 - threshold_high
        if proba > threshold_high:
            action = "BUY"
            confidence = (proba - threshold_high) / threshold_low
            signal_score = proba * 2 - 1
        elif proba < threshold_low:
            action = "SELL"
            confidence = (threshold_low - proba) / threshold_low
            signal_score = proba * 2 - 1
        else:
            action = "HOLD"
            confidence = 1.0 - abs(proba - 0.5) * 10
            signal_score = 0.0

        return {
            "action": action,
            "confidence": round(min(confidence, 1.0), 2),
            "signal_score": round(signal_score, 3),
            "probability": round(proba, 3),
        }

    def score(self, df: pd.DataFrame) -> float:
        features = prepare_features(df)
        if features.empty or len(features) < settings.ml_min_train_rows:
            return 0.0
        lookahead = settings.ml_lookahead
        threshold = settings.ml_threshold
        future_returns = df["close"].shift(-lookahead) / df["close"] - 1
        aligned = features.iloc[:-lookahead].copy()
        labels = np.asarray(future_returns.iloc[: len(aligned)].values).astype(float)
        y = np.where(labels > threshold, 1, np.where(labels < -threshold, 0, np.nan))
        mask = ~np.isnan(y)
        if mask.sum() < settings.ml_min_train_rows or self._model is None:
            return 0.0
        x_test = aligned[mask]
        try:
            preds = self._model.predict(x_test)
        except Exception:
            base = aligned[mask][BASE_FEATURE_COLS]
            preds = self._model.predict(base)
        y_test = y[mask].astype(int)
        return float(np.mean(preds == y_test))

    def fit(self, x_train: Any, y_train: Any) -> None:
        self._model = self._create_model()
        self._model.fit(x_train, y_train)

    def _predict_latest(self, features: pd.DataFrame) -> float:
        latest = features.iloc[-1:]
        try:
            return float(self._model.predict_proba(latest)[0, 1])
        except Exception:
            base = features[BASE_FEATURE_COLS].iloc[-1:]
            return float(self._model.predict_proba(base)[0, 1])

    def _train_on_the_fly(
        self, df: pd.DataFrame, features: pd.DataFrame, anomaly_mask: np.ndarray | None = None,
    ) -> tuple[Any, dict[str, Any] | None] | None:
        try:
            lookahead = settings.ml_lookahead
            threshold = settings.ml_threshold
            y, mask = build_labels(df["close"], lookahead=lookahead, threshold=threshold)
            n = min(len(features), len(y))
            aligned = features.iloc[:n].copy()
            y = y[:n]
            mask = mask[:n]
            if anomaly_mask is not None:
                am = anomaly_mask[:n]
                mask = mask & (~am)
            x_all = aligned[mask].values
            y_all = y[mask].astype(int)

            if len(x_all) < settings.ml_min_train_rows:
                return None

            splits = temporal_split(len(x_all))
            train_slice = splits["train"]
            val_slice = splits["val"]

            x_train = x_all[train_slice]
            y_train = y_all[train_slice]

            val_metrics = None
            if len(x_train) < settings.ml_min_train_rows:
                x_train = x_all
                y_train = y_all
            else:
                x_val = x_all[val_slice]
                y_val = y_all[val_slice]

            model = self._create_model()
            model.fit(x_train, y_train)

            if val_slice.start < val_slice.stop and len(x_val) > 0:
                preds = model.predict(x_val)
                val_metrics = compute_classification_metrics(y_val, preds)
                baseline_acc = baseline_accuracy(df["close"], y, mask, val_slice, y_val)
                logger.info(
                    "%s — val acc=%.3f prec=%.3f rec=%.3f f1=%.3f baseline=%.3f (%d samples)",
                    self.model_name,
                    val_metrics["accuracy"],
                    val_metrics["precision"],
                    val_metrics["recall"],
                    val_metrics["f1"],
                    baseline_acc,
                    len(y_val),
                )
                if baseline_acc > 0:
                    logger.info(
                        "%s — vs baseline: model=%.3f baseline=%.3f delta=%.3f",
                        self.model_name,
                        val_metrics["accuracy"],
                        baseline_acc,
                        val_metrics["accuracy"] - baseline_acc,
                    )
                log_shap(model, x_train, x_val, self.model_name, self._feature_names())

            return model, val_metrics
        except Exception as e:
            logger.warning("%s training failed: %s", self.model_name, e)
            return None

    def _feature_names(self) -> list[str]:
        return BASE_FEATURE_COLS + EVENT_FEATURE_COLS


class BaseRegressor(PersistMixin, ABC):
    def __init__(self, ticker: str = ""):
        self._model: Any = None
        self._ticker = ticker

    @abstractmethod
    def train(self, *args: Any, **kwargs: Any) -> Any: ...

    @abstractmethod
    def predict(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...
