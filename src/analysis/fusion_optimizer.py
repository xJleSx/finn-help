from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.signals.engine import BASE_WEIGHTS, WEIGHT_RANGES

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardFold:
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    best_weights: dict[str, float] | None = None
    best_threshold: float = 0.02
    train_accuracy: float = 0.0
    test_accuracy: float = 0.0
    sharpe: float = 0.0
    max_dd: float = 0.0


@dataclass
class OptimizationResult:
    folds: list[WalkForwardFold] = field(default_factory=list)
    recommended_weights: dict[str, float] | None = None
    recommended_threshold: float = 0.02
    oos_sharpe_avg: float = 0.0
    stability: float = 0.0


def _simulate_trades(signals: list[dict[str, Any]], weights: dict[str, float], threshold: float) -> tuple[float, float, float]:
    equity = [1.0]
    for sig in signals:
        w = _weighted_score(sig, weights)
        if w > threshold:
            equity.append(equity[-1] * (1 + sig.get("return_5d", 0)))
        elif w < -threshold:
            equity.append(equity[-1] * (1 - sig.get("return_5d", 0)))
    if len(equity) < 2:
        return 0.0, 0.0, 0.0
    rets = np.diff(equity) / equity[:-1]
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 1e-8 else 0.0
    running = np.maximum.accumulate(equity)
    dd = float(np.min((equity - running) / running))
    accuracy = float(np.mean([1.0 if (s.get("action_correct") and ((w := _weighted_score(s, weights)) > threshold or w < -threshold)) else 0.0 for s in signals])) if signals else 0.0
    return sharpe, dd, accuracy


def _weighted_score(sig: dict[str, Any], weights: dict[str, float]) -> float:
    return sum(weights.get(k, 0.0) * sig.get(k, 0.0) for k in weights)


def _walk_forward_split(data: list[dict[str, Any]], n_splits: int = 5, gap: int = 20) -> list[WalkForwardFold]:
    total = len(data)
    folds: list[WalkForwardFold] = []
    test_size = total // (n_splits + 1)
    for i in range(n_splits):
        test_start = (i + 1) * test_size
        test_end = min(test_start + test_size, total)
        train_start = 0
        train_end = test_start - gap
        if train_end > train_start:
            folds.append(WalkForwardFold(train_start=train_start, train_end=train_end, test_start=test_start, test_end=test_end))
    return folds


def optimize_weights(
    historical_signals: list[dict[str, Any]],
    n_splits: int = 5,
    gap: int = 20,
) -> OptimizationResult:
    if len(historical_signals) < 100:
        logger.warning("Not enough historical signals for WF optimization (%d < 100)", len(historical_signals))
        return OptimizationResult()

    folds = _walk_forward_split(historical_signals, n_splits, gap)
    components = list(BASE_WEIGHTS.keys())
    threshold_range = np.arange(0.005, 0.06, 0.005)

    results: list[WalkForwardFold] = []
    best_overall_sharpe = -1.0
    best_weights_overall: dict[str, float] | None = None
    best_threshold_overall = 0.02

    for fold in folds:
        train = historical_signals[fold.train_start:fold.train_end]
        test = historical_signals[fold.test_start:fold.test_end]
        if len(train) < 50 or len(test) < 20:
            continue

        best_fold_sharpe = -1.0
        best_fold_w: dict[str, float] = dict(BASE_WEIGHTS)
        best_fold_t = 0.02

        multipliers = [0.8, 1.0, 1.2]
        total_combinations = len(threshold_range) * (len(multipliers) ** len(components))
        n_iter = min(500, total_combinations)
        no_improve_count = 0
        best_so_far = -1.0

        for _ in range(n_iter):
            threshold = float(random.choice(threshold_range))
            combo = [random.choice(multipliers) for _ in components]
            w = {components[i]: BASE_WEIGHTS[components[i]] * combo[i] for i in range(len(components))}
            total = sum(w.values())
            w = {k: v / total for k, v in w.items()}
            for k, r in WEIGHT_RANGES.items():
                if k in w:
                    w[k] = max(r["min"], min(r["max"], w[k]))
            total = sum(w.values())
            w = {k: v / total for k, v in w.items()}

            s, dd, _ = _simulate_trades(train, w, float(threshold))
            if s > best_fold_sharpe:
                best_fold_sharpe = s
                best_fold_w = dict(w)
                best_fold_t = float(threshold)

            if s > best_so_far:
                best_so_far = s
                no_improve_count = 0
            else:
                no_improve_count += 1

            if no_improve_count >= max(10, n_iter // 10):
                break

        test_sharpe, test_dd, test_acc = _simulate_trades(test, best_fold_w, best_fold_t)
        fold.best_weights = best_fold_w
        fold.best_threshold = best_fold_t
        fold.train_accuracy = best_fold_sharpe
        fold.test_accuracy = test_acc
        fold.sharpe = test_sharpe
        fold.max_dd = test_dd
        results.append(fold)

        if test_sharpe > best_overall_sharpe:
            best_overall_sharpe = test_sharpe
            best_weights_overall = dict(best_fold_w)
            best_threshold_overall = best_fold_t

    if not results:
        return OptimizationResult()

    oos_sharpes = [r.sharpe for r in results]
    med = np.median(oos_sharpes) if oos_sharpes else 0.0
    stability = float(1.0 - np.std(oos_sharpes) / (abs(med) + 1e-6)) if med != 0 else 0.0

    logger.info(
        "WF optimization done: %d folds, OOS sharpe=%.3f, stability=%.2f, threshold=%.3f",
        len(results),
        float(np.mean(oos_sharpes)),
        stability,
        best_threshold_overall,
    )

    return OptimizationResult(
        folds=results,
        recommended_weights=best_weights_overall,
        recommended_threshold=best_threshold_overall,
        oos_sharpe_avg=float(np.mean(oos_sharpes)),
        stability=stability,
    )


def run_fusion_walk_forward(db_session: Any = None) -> OptimizationResult:
    from sqlalchemy import select

    from src.db.models import Signal as SignalModel

    if db_session is None:
        from src.db.connection import get_session
        db_session = get_session()

    rows = db_session.execute(
        select(SignalModel).order_by(SignalModel.date).where(SignalModel.date.isnot(None))
    ).scalars().all()

    signals: list[dict[str, Any]] = []
    for r in rows:
        try:
            components = r.components or {}
            sig = {
                "date": r.date,
                "return_5d": 0.0,
                "action_correct": False,
                "technical": components.get("technical_score", 0.0),
                "fundamental": components.get("fundamental_score", 0.0),
                "geo": components.get("geo_score", 0.0),
                "ml": components.get("ml_score", 0.0),
                "sentiment": components.get("sentiment_score", 0.0),
                "mtf": components.get("mtf_score", 0.0),
            }
            signals.append(sig)
        except Exception:
            continue

    logger.info("Loaded %d historical signals for WF optimization", len(signals))
    return optimize_weights(signals)
