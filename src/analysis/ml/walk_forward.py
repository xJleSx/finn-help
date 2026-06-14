import logging

import numpy as np
from sklearn.model_selection import TimeSeriesSplit

logger = logging.getLogger(__name__)


def walk_forward_validate(
    x: np.ndarray,
    y: np.ndarray,
    model_factory,
    n_splits: int = 3,
    min_train_size: int = 60,
) -> dict:
    if len(x) < min_train_size + 10:
        return {"oos_accuracy": 0.5, "oos_precision": 0.0, "oos_recall": 0.0, "folds_completed": 0}

    tscv = TimeSeriesSplit(n_splits=n_splits)

    accuracies = []
    precisions = []
    recalls = []
    folds = 0

    for train_idx, test_idx in tscv.split(x):
        if len(train_idx) < min_train_size or len(test_idx) < 5:
            continue

        x_train, x_test = x[train_idx], x[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        try:
            model = model_factory()
            model.fit(x_train, y_train)
            preds = model.predict(x_test)

            acc = float(np.mean(preds == y_test))
            accuracies.append(acc)

            tp = ((preds == 1) & (y_test == 1)).sum()
            fp = ((preds == 1) & (y_test == 0)).sum()
            fn = ((preds == 0) & (y_test == 1)).sum()

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

            precisions.append(precision)
            recalls.append(recall)
            folds += 1
        except Exception as e:
            logger.warning(f"Walk-forward fold {folds + 1} failed: {e}")
            continue

    if folds == 0:
        return {"oos_accuracy": 0.5, "oos_precision": 0.0, "oos_recall": 0.0, "folds_completed": 0}

    return {
        "oos_accuracy": round(float(np.mean(accuracies)), 3),
        "oos_precision": round(float(np.mean(precisions)), 3) if precisions else 0.0,
        "oos_recall": round(float(np.mean(recalls)), 3) if recalls else 0.0,
        "folds_completed": folds,
    }


def adjust_confidence_by_oos(base_confidence: float, oos_metrics: dict) -> float:
    acc = oos_metrics.get("oos_accuracy", 0.5)
    folds = oos_metrics.get("folds_completed", 0)

    if folds == 0:
        return base_confidence

    bonus = (acc - 0.5) * 2.0
    adjusted = base_confidence * (1.0 + max(bonus, -0.5))
    return round(max(min(adjusted, 1.0), 0.0), 2)
