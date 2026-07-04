from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from src.trading.metrics import PerformanceMetrics

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    best_params: dict[str, Any] = field(default_factory=dict)
    best_score: float = 0.0
    trials: list[dict[str, Any]] = field(default_factory=list)
    n_trials: int = 0
    objective_name: str = "sharpe"


def optimize_grid_search(
    param_grid: dict[str, list[Any]],
    eval_fn: Callable[[dict[str, Any]], PerformanceMetrics],
    maximize: str = "sharpe",
) -> OptimizationResult:
    from itertools import product

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    result = OptimizationResult(objective_name=maximize)
    best_score = float("-inf")

    for combo in product(*values):
        params = dict(zip(keys, combo))
        try:
            metrics = eval_fn(params)
            score = getattr(metrics, maximize, 0.0) or 0.0
            result.trials.append({"params": params, "score": score, **metrics.to_dict()})
            if score > best_score:
                best_score = score
                result.best_params = params
                result.best_score = score
        except Exception as e:
            logger.warning("Grid search trial failed: %s", e)
            continue

    result.n_trials = len(result.trials)
    logger.info("Grid search completed: %d trials, best %s=%.4f", result.n_trials, maximize, result.best_score)
    return result


def optimize_optuna(
    eval_fn: Callable[[dict[str, Any]], PerformanceMetrics],
    suggest_fn: Callable,
    n_trials: int = 100,
    maximize: str = "sharpe",
    study_name: str = "strategy_optimization",
    storage: str | None = None,
    timeout: int | None = None,
) -> OptimizationResult:
    try:
        import optuna
    except ImportError:
        logger.warning("optuna not installed. Run: pip install optuna")
        return OptimizationResult(n_trials=0)

    def objective(trial: optuna.Trial) -> float:
        params = suggest_fn(trial)
        try:
            metrics = eval_fn(params)
            score = getattr(metrics, maximize, 0.0) or 0.0
            return float(score)
        except Exception as e:
            logger.warning("Trial failed: %s", e)
            return float("-inf")

    study = optuna.create_study(
        direction="maximize",
        study_name=study_name,
        storage=storage,
        load_if_exists=True,
    )
    study.optimize(objective, n_trials=n_trials, timeout=timeout)

    result = OptimizationResult(
        best_params=study.best_params if study.best_params else {},
        best_score=float(study.best_value) if study.best_value else 0.0,
        n_trials=len(study.trials),
        objective_name=maximize,
    )
    for t in study.trials:
        if t.value is not None and t.params:
            result.trials.append({"params": dict(t.params), "score": float(t.value)})

    logger.info("Optuna optimization: %d trials, best %s=%.4f", result.n_trials, maximize, result.best_score)
    return result


OptimizeResult = OptimizationResult
