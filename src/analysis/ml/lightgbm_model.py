import logging
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd

from src.analysis.ml.walk_forward import (
    baseline_accuracy,
    build_labels,
    compute_classification_metrics,
    temporal_split,
)
from src.model_registry import load_model as load_from_registry
from src.model_registry import save_model

logger = logging.getLogger(__name__)


class LightGBMClassifier:
    def __init__(self, ticker: str = ""):
        self._model: Optional = None
        self._ticker = ticker

    @property
    def model_name(self) -> str:
        return f"lgb_{self._ticker}" if self._ticker else "lgb"

    def save(self, metrics: Optional[dict] = None) -> str:
        if self._model is None:
            raise ValueError("No trained model to save")
        return save_model(self._model, self.model_name, metrics=metrics)

    def load(self, version: Optional[str] = None):
        self._model = load_from_registry(self.model_name, version=version)
        return self._model

    def train(self, df: pd.DataFrame) -> bool:
        features = self._prepare_features(df)
        if features.empty or len(features) < 30:
            return False
        result = self._train_on_the_fly(df, features)
        if result is None:
            return False
        model, val_metrics = result
        self._model = model
        save_metrics = {"rows": len(features), "ticker": self._ticker}
        if val_metrics:
            save_metrics["val_accuracy"] = val_metrics.get("accuracy", 0)
            save_metrics["val_precision"] = val_metrics.get("precision", 0)
            save_metrics["val_recall"] = val_metrics.get("recall", 0)
            save_metrics["val_f1"] = val_metrics.get("f1", 0)
        self.save(metrics=save_metrics)
        return True

    def predict(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < 60:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        features = self._prepare_features(df)
        if features.empty or len(features) < 30:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        model = self._model
        if model is None:
            try:
                model = self.load()
            except (ValueError, FileNotFoundError):
                pass

        if model is None:
            result = self._train_on_the_fly(df, features)
            if result is not None:
                model, _ = result
                if model is not None:
                    self._model = model
                    self.save(metrics={"rows": len(features), "ticker": self._ticker})

        if model is None:
            return {"action": "NEUTRAL", "confidence": 0.0, "signal_score": 0.0}

        latest = features.iloc[-1:].values
        proba = model.predict_proba(latest)[0, 1]

        if proba > 0.55:
            action = "BUY"
            confidence = (proba - 0.55) / 0.45
            signal_score = proba * 2 - 1
        elif proba < 0.45:
            action = "SELL"
            confidence = (0.45 - proba) / 0.45
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
        """Return accuracy on a held-out set if model is trained."""
        features = self._prepare_features(df)
        if features.empty or len(features) < 20:
            return 0.0
        lookahead = 5
        threshold = 0.03
        future_returns = df["close"].shift(-lookahead) / df["close"] - 1
        aligned = features.iloc[:-lookahead].copy()
        labels = future_returns.iloc[: len(aligned)].values
        y = np.where(labels > threshold, 1, np.where(labels < -threshold, 0, np.nan))
        mask = ~np.isnan(y)
        if mask.sum() < 10 or self._model is None:
            return 0.0
        x_test = aligned[mask].values
        y_test = y[mask].astype(int)
        preds = self._model.predict(x_test)
        return float(np.mean(preds == y_test))

    def fit(self, x_train, y_train):
        """Standalone fit for walk-forward validation."""
        self._model = lgb.LGBMClassifier(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.1,
            verbosity=-1,
            deterministic=True,
        )
        self._model.fit(x_train, y_train)

    EVENT_FEATURE_COLS = ["event_count_30d", "event_severity_30d", "sanctions_30d", "days_since_major_event"]

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        needed = ["rsi", "macd_hist", "sma_20", "sma_50", "close"]
        if not all(c in df.columns for c in needed):
            return pd.DataFrame()

        result = df[needed].copy()
        result["price_sma20"] = result["close"] / result["sma_20"].replace(0, np.nan)
        result["price_sma50"] = result["close"] / result["sma_50"].replace(0, np.nan)
        result["sma20_sma50"] = result["sma_20"] / result["sma_50"].replace(0, np.nan)
        result["rsi_norm"] = result["rsi"] / 100
        result["macd_signal_binary"] = (result["macd_hist"] > 0).astype(int)
        for c in self.EVENT_FEATURE_COLS:
            if c in df.columns:
                result[c] = df[c].values
        result = result.dropna()
        return result

    def _train_on_the_fly(self, df: pd.DataFrame, features: pd.DataFrame):
        try:
            lookahead = 5
            threshold = 0.03
            y, mask = build_labels(df["close"], lookahead=lookahead, threshold=threshold)
            aligned = features.iloc[: len(y)].copy()
            x_all = aligned[mask].values
            y_all = y[mask].astype(int)

            if len(x_all) < 30:
                return None

            splits = temporal_split(len(x_all))
            train_slice = splits["train"]
            val_slice = splits["val"]

            x_train = x_all[train_slice]
            y_train = y_all[train_slice]

            if len(x_train) < 30:
                x_train = x_all
                y_train = y_all
                val_metrics = None
            else:
                x_val = x_all[val_slice]
                y_val = y_all[val_slice]

            model = lgb.LGBMClassifier(
                n_estimators=50,
                max_depth=3,
                learning_rate=0.1,
                verbosity=-1,
                deterministic=True,
            )
            model.fit(x_train, y_train)

            val_metrics = None
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
                self._log_shap(model, x_train, x_val)

            return model, val_metrics
        except Exception as e:
            logger.warning(f"LightGBM training failed: {e}")
            return None

    def _log_shap(self, model, x_train: np.ndarray, x_val: np.ndarray):
        try:
            import shap
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(x_val)
            mean_abs = np.mean(np.abs(shap_values), axis=0)
            if len(mean_abs) > 0:
                top_k = min(5, len(mean_abs))
                top_idx = np.argsort(mean_abs)[-top_k:][::-1]
                feature_names = self._feature_names()
                parts = [f"{feature_names[i]}:{mean_abs[i]:.4f}" for i in top_idx]
                logger.info("%s — SHAP top features: %s", self.model_name, " ".join(parts))
        except Exception as e:
            logger.debug("SHAP unavailable: %s", e)

    def _feature_names(self) -> list[str]:
        names = [
            "close", "rsi", "macd_hist", "sma_20", "sma_50",
            "price_sma20", "price_sma50", "sma20_sma50", "rsi_norm", "macd_signal_binary",
        ]
        return names + self.EVENT_FEATURE_COLS
