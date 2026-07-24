from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analysis.optimizer import (
    OptimizationResult,
    optimize_grid_search,
    optimize_optuna,
)
from src.trading.metrics import PerformanceMetrics


def _make_metrics(sharpe=1.0):
    return PerformanceMetrics(sharpe=sharpe, total_return=sharpe * 0.1)


class TestOptimizationResult:
    def test_default_values(self):
        r = OptimizationResult()
        assert r.best_params == {}
        assert r.best_score == 0.0
        assert r.trials == []
        assert r.n_trials == 0
        assert r.objective_name == "sharpe"


class TestOptimizeGridSearch:
    def test_empty_param_grid_yields_one_trial(self):
        result = optimize_grid_search({}, lambda p: _make_metrics())
        assert result.n_trials == 1
        assert result.best_params == {}

    def test_single_param_single_value(self):
        result = optimize_grid_search(
            {"lookback": [20]},
            lambda p: _make_metrics(sharpe=1.5),
        )
        assert result.n_trials == 1
        assert result.best_params == {"lookback": 20}
        assert result.best_score == 1.5

    def test_picks_highest_score(self):
        scores = iter([0.5, 1.2, 0.8])

        def eval_fn(params):
            return _make_metrics(sharpe=next(scores))

        result = optimize_grid_search(
            {"param": [1, 2, 3]},
            eval_fn,
        )
        assert result.best_params == {"param": 2}
        assert result.best_score == 1.2

    def test_skips_failing_trials(self):
        call_count = 0

        def eval_fn(params):
            nonlocal call_count
            call_count += 1
            if params["x"] == 1:
                raise ValueError("fail")
            return _make_metrics(sharpe=float(params["x"]))

        result = optimize_grid_search({"x": [1, 2, 3]}, eval_fn)
        assert result.n_trials == 2
        assert result.best_score == 3.0

    def test_trials_contain_metrics_dict(self):
        def eval_fn(params):
            return _make_metrics(sharpe=float(params["n"]))

        result = optimize_grid_search({"n": [10]}, eval_fn)
        assert len(result.trials) == 1
        trial = result.trials[0]
        assert trial["params"] == {"n": 10}
        assert trial["score"] == 10.0
        assert "sharpe" in trial

    def test_custom_maximize_field(self):
        def eval_fn(params):
            return PerformanceMetrics(sharpe=0.5, total_return=float(params["r"]))

        result = optimize_grid_search(
            {"r": [0.1, 0.2]},
            eval_fn,
            maximize="total_return",
        )
        assert result.objective_name == "total_return"
        assert result.best_params == {"r": 0.2}
        assert result.best_score == 0.2


class TestOptimizeOptuna:
    def test_returns_empty_when_optuna_not_installed(self):
        with patch.dict("sys.modules", {"optuna": None}):
            import importlib

            import src.analysis.optimizer

            importlib.reload(src.analysis.optimizer)
            from src.analysis.optimizer import optimize_optuna

            result = optimize_optuna(
                eval_fn=lambda p: _make_metrics(),
                suggest_fn=lambda t: {},
                n_trials=10,
            )
            assert result.n_trials == 0
            assert result.best_score == 0.0

    def test_with_mock_optuna(self):
        mock_study = MagicMock()
        mock_study.best_params = {"lr": 0.1, "depth": 3}
        mock_study.best_value = 1.5
        mock_trial_ok = MagicMock()
        mock_trial_ok.value = 1.5
        mock_trial_ok.params = {"lr": 0.1, "depth": 3}
        mock_trial_fail = MagicMock()
        mock_trial_fail.value = None
        mock_trial_fail.params = {}
        mock_study.trials = [mock_trial_ok, mock_trial_fail]

        mock_create_study = MagicMock(return_value=mock_study)
        mock_optuna = MagicMock()
        mock_optuna.create_study = mock_create_study
        mock_optuna.Trial = MagicMock

        def mock_suggest(trial):
            return {"lr": 0.1, "depth": 3}

        with patch.dict("sys.modules", {"optuna": mock_optuna}):
            result = optimize_optuna(
                eval_fn=lambda p: _make_metrics(sharpe=1.5),
                suggest_fn=mock_suggest,
                n_trials=5,
            )
            assert result.best_params == {"lr": 0.1, "depth": 3}
            assert result.best_score == 1.5
            assert result.n_trials == 2
            assert len(result.trials) == 1
            assert result.trials[0]["params"]["lr"] == 0.1

    def test_objective_returns_neg_inf_on_failure(self):
        mock_study = MagicMock()
        mock_study.best_params = {}
        mock_study.best_value = None
        mock_study.trials = []

        mock_optuna = MagicMock()
        mock_optuna.create_study = MagicMock(return_value=mock_study)
        mock_optuna.Trial = MagicMock

        def failing_eval(params):
            raise RuntimeError("fail")

        with patch.dict("sys.modules", {"optuna": mock_optuna}):
            result = optimize_optuna(
                eval_fn=failing_eval,
                suggest_fn=lambda t: {},
                n_trials=3,
            )
            assert result.best_params == {}
            assert result.best_score == 0.0
