from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

from src.analysis.ml.drift.adwin import ADWINDetector
from src.model_registry import save_model

logger = logging.getLogger(__name__)


class IncrementalTrainer:
    def partial_fit(self, model: Any, X: np.ndarray, y: np.ndarray, feature_names: list[str] | None = None) -> Any:
        model_type = type(model).__module__

        if "xgboost" in model_type:
            X_in = pd.DataFrame(X, columns=feature_names) if feature_names is not None else X
            model.fit(X_in, y, xgb_model=model.get_booster())
        elif "lightgbm" in model_type:
            model.fit(X, y, init_model=model, feature_name=feature_names)
        else:
            model.fit(X, y)
        return model

    def evaluate(self, model: Any, X_test: np.ndarray, y_test: np.ndarray) -> dict[str, float]:
        preds = model.predict(X_test)
        return {
            "accuracy": float(accuracy_score(y_test, preds)),
            "precision": float(precision_score(y_test, preds, zero_division=0)),
            "recall": float(recall_score(y_test, preds, zero_division=0)),
            "f1": float(f1_score(y_test, preds, zero_division=0)),
        }

    def monitor_and_retrain(
        self,
        model: Any,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_test: np.ndarray,
        y_test: np.ndarray,
        detector: ADWINDetector,
        metric_fn: Callable[[Any, np.ndarray, np.ndarray], float],
    ) -> dict[str, Any]:
        metric = metric_fn(model, X_test, y_test)
        drifted = detector.add_element(metric)

        result: dict[str, Any] = {
            "drift_detected": drifted,
            "current_metric": metric,
            "window_size": detector.get_width(),
            "window_mean": detector.get_mean(),
            "retrained": False,
        }

        if drifted:
            logger.info("Drift detected (metric=%.4f), retraining model", metric)
            self.partial_fit(model, X_train, y_train, feature_names=None)
            result["retrained"] = True

        return result


class ConceptDriftPipeline:
    def __init__(
        self,
        model: Any,
        detector: ADWINDetector | None = None,
        trainer: IncrementalTrainer | None = None,
        model_name: str = "concept_drift_model",
    ):
        self.model = model
        self.detector = detector or ADWINDetector()
        self.trainer = trainer or IncrementalTrainer()
        self.model_name = model_name
        self.drift_events: list[int] = []
        self.retrain_count = 0
        self._batch_counter = 0

    def process_batch(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str] | None = None,
    ) -> dict[str, Any]:
        from sklearn.model_selection import train_test_split

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        self.trainer.partial_fit(self.model, X_train, y_train, feature_names=feature_names)
        metrics = self.trainer.evaluate(self.model, X_test, y_test)

        self._batch_counter += 1

        result = self.trainer.monitor_and_retrain(
            model=self.model,
            X_train=X_train,
            y_train=y_train,
            X_test=X_test,
            y_test=y_test,
            detector=self.detector,
            metric_fn=lambda m, x, y: self.trainer.evaluate(m, x, y)["accuracy"],
        )

        if result["drift_detected"]:
            self.drift_events.append(self._batch_counter)
            self.retrain_count += 1
            save_model(self.model, self.model_name, metrics=metrics)

        return {
            "batch": self._batch_counter,
            "drift_detected": result["drift_detected"],
            "retrain_count": self.retrain_count,
            "total_drift_events": len(self.drift_events),
            "metrics": metrics,
            "window_size": result["window_size"],
            "window_mean": result["window_mean"],
        }
