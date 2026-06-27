import copy
import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

OOS_ACC_MIN = 0.52
TRAIN_VAL_TEST_SPLIT = (0.6, 0.2, 0.2)
GAP_SIZE = 20


def temporal_split(n: int, gap: int = GAP_SIZE) -> dict[str, slice]:
    """Split n rows into train/val/test by time with gaps.
    Returns slice objects for each partition.
    """
    train_end = int(n * TRAIN_VAL_TEST_SPLIT[0])
    val_end = train_end + gap + int(n * TRAIN_VAL_TEST_SPLIT[1])
    total_used = val_end + gap + int(n * TRAIN_VAL_TEST_SPLIT[2])

    if total_used > n:
        val_end = n - gap - int(n * TRAIN_VAL_TEST_SPLIT[2])
        if val_end <= train_end + gap:
            return {"train": slice(0, train_end), "val": slice(0, 0), "test": slice(0, 0)}

    return {
        "train": slice(0, train_end),
        "val": slice(train_end + gap, val_end),
        "test": slice(val_end + gap, n),
    }


def build_labels(close_series: pd.Series, lookahead: int = 5, threshold: float = 0.03) -> tuple[np.ndarray, np.ndarray]:
    """Generate binary labels from close prices with lookahead."""
    future_returns = close_series.shift(-lookahead) / close_series - 1
    y = np.where(future_returns > threshold, 1, np.where(future_returns < -threshold, 0, np.nan))
    mask = ~np.isnan(y)
    return y, mask


def walk_forward_validate(
    model_instance: Any,
    x: np.ndarray,
    y: np.ndarray,
    n_splits: int = 3,
    min_train_size: int = 60,
    gap: int = GAP_SIZE,
) -> dict[str, Any]:
    if len(x) < min_train_size + 10:
        return {"oos_accuracy": 0.5, "oos_precision": 0.0, "oos_recall": 0.0, "folds_completed": 0, "f1": 0.0}

    n = len(x)
    fold_size = (n - min_train_size) // n_splits
    if fold_size < 5:
        return {"oos_accuracy": 0.5, "oos_precision": 0.0, "oos_recall": 0.0, "folds_completed": 0, "f1": 0.0}

    accuracies = []
    precisions = []
    recalls = []
    f1_scores = []
    folds = 0

    for i in range(n_splits):
        test_end = n - i * fold_size
        test_start = max(test_end - fold_size, min_train_size + gap)

        train_end = test_start - gap
        if train_end < min_train_size:
            continue

        x_train, x_test = x[:train_end], x[test_start:test_end]
        y_train, y_test = y[:train_end], y[test_start:test_end]

        if len(x_test) < 5:
            continue

        try:
            model = copy.deepcopy(model_instance)
            if hasattr(model, "_model"):
                model._model = None
            model.fit(x_train, y_train)
            if hasattr(model, "_model") and model._model is not None:
                preds = model._model.predict(x_test)
            else:
                preds = model.predict(x_test)

            acc = float(np.mean(preds == y_test))
            accuracies.append(acc)

            tp = ((preds == 1) & (y_test == 1)).sum()
            fp = ((preds == 1) & (y_test == 0)).sum()
            fn = ((preds == 0) & (y_test == 1)).sum()

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

            precisions.append(precision)
            recalls.append(recall)
            f1_scores.append(f1)
            folds += 1
        except Exception as e:
            logger.warning(f"Walk-forward fold {folds + 1} failed: {e}")
            continue

    if folds == 0:
        return {"oos_accuracy": 0.5, "oos_precision": 0.0, "oos_recall": 0.0, "folds_completed": 0, "f1": 0.0}

    return {
        "oos_accuracy": round(float(np.mean(accuracies)), 3),
        "oos_precision": round(float(np.mean(precisions)), 3) if precisions else 0.0,
        "oos_recall": round(float(np.mean(recalls)), 3) if recalls else 0.0,
        "f1": round(float(np.mean(f1_scores)), 3) if f1_scores else 0.0,
        "folds_completed": folds,
    }


def adjust_confidence_by_oos(base_confidence: float, oos_metrics: dict[str, Any]) -> float:
    acc = oos_metrics.get("oos_accuracy", 0.5)
    folds = oos_metrics.get("folds_completed", 0)

    if folds == 0 or acc < OOS_ACC_MIN:
        return 0.0

    bonus = (acc - 0.5) * 2.0
    adjusted = base_confidence * (1.0 + max(bonus, -0.5))
    return float(round(max(min(adjusted, 1.0), 0.0), 2))


def model_weight_from_oos(oos_metrics: dict[str, Any]) -> float:
    """Return model weight based on OOS accuracy. 0 if below threshold."""
    acc = oos_metrics.get("oos_accuracy", 0.5)
    folds = oos_metrics.get("folds_completed", 0)
    if folds == 0 or acc < OOS_ACC_MIN:
        return 0.0
    return float(round((acc - 0.5) * 4 * min(folds / 3, 1), 3))


def baseline_accuracy(
    close_series: pd.Series, y: np.ndarray, mask: np.ndarray, val_slice: slice, y_val: np.ndarray
) -> float:
    close_vals: np.ndarray = np.asarray(close_series.iloc[: len(y)].values).astype(float)
    prev_close = np.roll(close_vals, 1)
    prev_close[0] = close_vals[0]
    baseline_preds = (close_vals > prev_close).astype(int)
    baseline_val = baseline_preds[mask][val_slice]
    return float(np.mean(baseline_val == y_val)) if len(baseline_val) > 0 else 0.0


def compute_classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    tp = ((y_pred == 1) & (y_true == 1)).sum()
    fp = ((y_pred == 1) & (y_true == 0)).sum()
    fn = ((y_pred == 0) & (y_true == 1)).sum()
    tn = ((y_pred == 0) & (y_true == 0)).sum()

    total = tp + fp + fn + tn
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "accuracy": round(float(accuracy), 3),
        "precision": round(float(precision), 3),
        "recall": round(float(recall), 3),
        "f1": round(float(f1), 3),
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn),
    }
