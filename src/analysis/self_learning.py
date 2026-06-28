from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from src.db.models import ModelFeedback

logger = logging.getLogger(__name__)


@dataclass
class PredictionRecord:
    ticker: str
    model_name: str
    predicted_return: float
    actual_return: float
    prediction_date: datetime
    horizon_days: int
    features_hash: str


@dataclass
class ModelPerformance:
    model_name: str
    mae: float
    direction_accuracy: float
    samples: int
    last_updated: datetime


class SelfLearningEngine:
    def record_prediction(
        self, db: Any, ticker: str, model_name: str,
        predicted: float, actual: float, horizon: int,
        features_hash: str = "",
    ) -> ModelFeedback:
        record = ModelFeedback(
            ticker=ticker.upper(),
            model_name=model_name,
            predicted_return=predicted,
            actual_return=actual,
            prediction_date=datetime.now(timezone.utc),
            horizon_days=horizon,
            features_hash=features_hash,
        )
        db.add(record)
        db.commit()
        logger.info("Recorded %s %s: pred=%.4f actual=%.4f", ticker, model_name, predicted, actual)
        return record

    def evaluate_performance(
        self, db: Any, model_name: str, days_back: int = 30,
    ) -> ModelPerformance:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        rows = (
            db.query(ModelFeedback)
            .filter(
                ModelFeedback.model_name == model_name,
                ModelFeedback.prediction_date >= cutoff,
            )
            .all()
        )
        if not rows:
            return ModelPerformance(
                model_name=model_name,
                mae=0.0,
                direction_accuracy=0.0,
                samples=0,
                last_updated=datetime.now(timezone.utc),
            )

        preds = np.array([r.predicted_return for r in rows])
        actuals = np.array([r.actual_return for r in rows])
        mae = float(np.mean(np.abs(preds - actuals)))
        direction_acc = float(np.mean(
            (np.sign(preds) == np.sign(actuals)) | (np.abs(actuals) < 0.001)
        ))
        last = max(r.created_at or r.prediction_date for r in rows)

        return ModelPerformance(
            model_name=model_name,
            mae=round(mae, 4),
            direction_accuracy=round(direction_acc, 4),
            samples=len(rows),
            last_updated=last,
        )

    def should_retrain(
        self, db: Any, model_name: str,
        min_samples: int = 30, max_error: float = 0.05,
    ) -> bool:
        perf = self.evaluate_performance(db, model_name)
        if perf.samples < min_samples:
            return False
        return perf.mae > max_error

    def auto_retrain(self, db: Any, model_name: str) -> dict[str, Any]:
        if not self.should_retrain(db, model_name):
            return {"model_name": model_name, "retrained": False, "reason": "performance acceptable"}

        try:
            from src.analysis.ml.news_impact import NewsImpactModel

            rest = model_name[len("news_impact_"):]
            parts = rest.rsplit("_", 1)
            horizon_str = parts[-1]
            ticker = parts[0] if len(parts) > 1 else ""
            horizon = int(horizon_str[:-1])

            model = NewsImpactModel(ticker)
            result = model.train(db)
            return {
                "model_name": model_name,
                "retrained": True,
                "horizon": horizon,
                "ticker": ticker,
                **result,
            }
        except Exception as e:
            logger.exception("Auto-retrain failed for %s", model_name)
            return {"model_name": model_name, "retrained": False, "reason": str(e)}

    def compare_models(
        self, db: Any, model_a: str, model_b: str,
    ) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        rows_a = (
            db.query(ModelFeedback)
            .filter(
                ModelFeedback.model_name == model_a,
                ModelFeedback.features_hash != "",
                ModelFeedback.created_at >= cutoff,
            )
            .all()
        )
        rows_b = (
            db.query(ModelFeedback)
            .filter(
                ModelFeedback.model_name == model_b,
                ModelFeedback.features_hash != "",
                ModelFeedback.created_at >= cutoff,
            )
            .all()
        )

        by_hash_a: dict[str, list[ModelFeedback]] = {}
        for r in rows_a:
            by_hash_a.setdefault(r.features_hash, []).append(r)
        by_hash_b: dict[str, list[ModelFeedback]] = {}
        for r in rows_b:
            by_hash_b.setdefault(r.features_hash, []).append(r)

        common = set(by_hash_a) & set(by_hash_b)
        if not common:
            return {
                "model_a": model_a,
                "model_b": model_b,
                "paired_samples": 0,
                "conclusion": "insufficient paired data",
            }

        err_a, err_b = [], []
        dir_a, dir_b = [], []
        for fh in common:
            for ra in by_hash_a[fh]:
                err_a.append(abs(ra.predicted_return - ra.actual_return))
                dir_a.append(
                    np.sign(ra.predicted_return) == np.sign(ra.actual_return)
                    or abs(ra.actual_return) < 0.001
                )
            for rb in by_hash_b[fh]:
                err_b.append(abs(rb.predicted_return - rb.actual_return))
                dir_b.append(
                    np.sign(rb.predicted_return) == np.sign(rb.actual_return)
                    or abs(rb.actual_return) < 0.001
                )

        mae_a = float(np.mean(err_a))
        mae_b = float(np.mean(err_b))
        dir_acc_a = float(np.mean(dir_a))
        dir_acc_b = float(np.mean(dir_b))

        if mae_a < mae_b and dir_acc_a >= dir_acc_b:
            winner = model_a
        elif mae_b < mae_a and dir_acc_b >= dir_acc_a:
            winner = model_b
        elif dir_acc_a > dir_acc_b:
            winner = model_a
        elif dir_acc_b > dir_acc_a:
            winner = model_b
        else:
            winner = "tie"

        return {
            "model_a": model_a,
            "model_b": model_b,
            "paired_samples": sum(len(by_hash_a[fh]) + len(by_hash_b[fh]) for fh in common),
            f"{model_a}_mae": round(mae_a, 4),
            f"{model_b}_mae": round(mae_b, 4),
            f"{model_a}_direction_accuracy": round(dir_acc_a, 4),
            f"{model_b}_direction_accuracy": round(dir_acc_b, 4),
            "winner": winner,
        }

    @staticmethod
    def features_hash(features: dict[str, float]) -> str:
        raw = json.dumps(features, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
