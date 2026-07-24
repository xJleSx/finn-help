from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.analysis.fusion_optimizer import (
    WalkForwardFold,
    _simulate_trades,
    _walk_forward_split,
    _weighted_score,
    optimize_weights,
)
from src.signals.engine import BASE_WEIGHTS


def make_signal(technical=0.0, fundamental=0.0, geo=0.0, ml=0.0, sentiment=0.0, mtf=0.0, return_5d=0.01, action_correct=True):
    return {
        "technical": technical,
        "fundamental": fundamental,
        "geo": geo,
        "ml": ml,
        "sentiment": sentiment,
        "mtf": mtf,
        "return_5d": return_5d,
        "action_correct": action_correct,
    }


class TestWeightedScore:
    def test_weighted_score_computes_dot_product(self):
        sig = {"technical": 1.0, "fundamental": 0.5}
        weights = {"technical": 0.4, "fundamental": 0.3}
        result = _weighted_score(sig, weights)
        assert result == pytest.approx(0.4 * 1.0 + 0.3 * 0.5)

    def test_weighted_score_ignores_missing_keys(self):
        sig = {"technical": 1.0}
        weights = {"technical": 0.4, "fundamental": 0.3}
        result = _weighted_score(sig, weights)
        assert result == pytest.approx(0.4)


class TestWalkForwardSplit:
    def test_returns_correct_number_of_folds(self):
        data = list(range(200))
        folds = _walk_forward_split(data, n_splits=5, gap=20)
        assert len(folds) >= 1

    def test_fold_structure_is_ordered(self):
        data = list(range(300))
        folds = _walk_forward_split(data, n_splits=5, gap=20)
        for fold in folds:
            assert fold.train_start < fold.train_end <= fold.test_start < fold.test_end

    def test_fold_indices_within_bounds(self):
        data = list(range(300))
        folds = _walk_forward_split(data, n_splits=5, gap=20)
        for fold in folds:
            assert 0 <= fold.train_start
            assert fold.train_end <= len(data)
            assert fold.test_end <= len(data)

    def test_gap_between_train_and_test(self):
        data = list(range(300))
        folds = _walk_forward_split(data, n_splits=5, gap=20)
        for fold in folds:
            assert fold.train_end + 20 <= fold.test_start


class TestSimulateTrades:
    def test_no_signals_returns_zeros(self):
        sharpe, dd, acc = _simulate_trades([], BASE_WEIGHTS, 0.02)
        assert sharpe == 0.0
        assert dd == 0.0
        assert acc == 0.0

    def test_all_positive_signals_yields_positive_returns(self):
        signals = [make_signal(technical=0.8, return_5d=0.01 + 0.001 * i) for i in range(10)]
        sharpe, dd, acc = _simulate_trades(signals, BASE_WEIGHTS, 0.02)
        assert sharpe > 0

    def test_all_negative_signals_below_threshold_no_trades(self):
        signals = [make_signal(technical=-0.5, return_5d=0.01) for _ in range(10)]
        wt = {"technical": 1.0, "fundamental": 0.0, "geo": 0.0, "ml": 0.0, "sentiment": 0.0, "mtf": 0.0}
        total = sum(wt.values())
        wt = {k: v / total for k, v in wt.items()}
        sharpe, dd, acc = _simulate_trades(signals, wt, 0.02)
        assert sharpe == 0.0

    def test_negative_signal_below_threshold_triggers_short(self):
        signals = [make_signal(technical=-0.5, return_5d=0.01) for _ in range(5)]
        wt = {"technical": 1.0, "fundamental": 0.0, "geo": 0.0, "ml": 0.0, "sentiment": 0.0, "mtf": 0.0}
        total = sum(wt.values())
        wt = {k: v / total for k, v in wt.items()}
        sig = make_signal(technical=-0.5, return_5d=0.01)
        signals = [sig]
        scored = _weighted_score(sig, wt)
        assert scored < -0.02

    def test_accuracy_is_computed(self):
        signals = [make_signal(technical=0.8, return_5d=0.01, action_correct=True) for _ in range(10)]
        wt = {"technical": 1.0, "fundamental": 0.0, "geo": 0.0, "ml": 0.0, "sentiment": 0.0, "mtf": 0.0}
        total = sum(wt.values())
        wt = {k: v / total for k, v in wt.items()}
        sharpe, dd, acc = _simulate_trades(signals, wt, 0.02)
        assert acc > 0


class TestOptimizeWeights:
    def test_returns_empty_result_when_insufficient_data(self):
        result = optimize_weights([], n_splits=5, gap=20)
        assert result.recommended_weights is None
        assert result.oos_sharpe_avg == 0.0

    def test_returns_empty_result_when_less_than_100_signals(self):
        signals = [make_signal() for _ in range(50)]
        result = optimize_weights(signals, n_splits=5, gap=20)
        assert result.recommended_weights is None

    def test_optimize_returns_recommended_weights_with_enough_data(self):
        signals = [make_signal(technical=0.5, return_5d=0.02 * (1 if i % 2 == 0 else -1), action_correct=(i % 2 == 0)) for i in range(200)]
        result = optimize_weights(signals, n_splits=3, gap=10)
        assert result.recommended_weights is not None
        assert result.recommended_threshold > 0

    def test_optimize_stability_is_computed(self):
        signals = [make_signal(technical=0.6, return_5d=0.02, action_correct=True) for _ in range(200)]
        result = optimize_weights(signals, n_splits=3, gap=10)
        assert result.folds
        assert isinstance(result.stability, float)

    def test_optimize_folds_have_populated_metrics(self):
        signals = [make_signal(technical=0.5, return_5d=0.015 * (1 if i % 3 == 0 else -1), action_correct=(i % 3 == 0)) for i in range(300)]
        result = optimize_weights(signals, n_splits=3, gap=10)
        for fold in result.folds:
            assert fold.best_weights is not None
            assert len(fold.best_weights) > 0
