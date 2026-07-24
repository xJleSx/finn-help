from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.self_learning import ModelPerformance, PredictionRecord, SelfLearningEngine


class TestRecordPrediction:
    def test_record_prediction_creates_and_returns_feedback(self):
        db = MagicMock()
        engine = SelfLearningEngine()
        record = engine.record_prediction(db, "SBER", "test_model", 0.05, 0.03, 5)
        assert record.ticker == "SBER"
        assert record.model_name == "test_model"
        assert record.predicted_return == 0.05
        assert record.actual_return == 0.03
        assert record.horizon_days == 5
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_record_prediction_upper_cases_ticker(self):
        db = MagicMock()
        engine = SelfLearningEngine()
        record = engine.record_prediction(db, "sber", "test_model", 0.05, 0.03, 5)
        assert record.ticker == "SBER"

    def test_record_prediction_accepts_features_hash(self):
        db = MagicMock()
        engine = SelfLearningEngine()
        record = engine.record_prediction(db, "SBER", "test_model", 0.05, 0.03, 5, features_hash="abc123")
        assert record.features_hash == "abc123"


class TestEvaluatePerformance:
    def test_no_data_returns_empty_performance(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        engine = SelfLearningEngine()
        perf = engine.evaluate_performance(db, "test_model")
        assert perf.samples == 0
        assert perf.mae == 0.0
        assert perf.direction_accuracy == 0.0

    def test_mae_and_direction_accuracy_computed_correctly(self):
        db = MagicMock()
        r1 = MagicMock(predicted_return=0.10, actual_return=0.08, created_at=None, prediction_date=datetime.now(timezone.utc))
        r2 = MagicMock(predicted_return=-0.05, actual_return=-0.04, created_at=None, prediction_date=datetime.now(timezone.utc))
        r3 = MagicMock(predicted_return=0.02, actual_return=-0.01, created_at=None, prediction_date=datetime.now(timezone.utc))
        db.query.return_value.filter.return_value.all.return_value = [r1, r2, r3]
        engine = SelfLearningEngine()
        perf = engine.evaluate_performance(db, "test_model")
        expected_mae = (abs(0.10 - 0.08) + abs(-0.05 - (-0.04)) + abs(0.02 - (-0.01))) / 3
        assert perf.mae == pytest.approx(expected_mae, rel=1e-4)
        # directions: (+, +) correct, (-, -) correct, (+, -) wrong -> 2/3
        assert perf.direction_accuracy == pytest.approx(2 / 3, rel=1e-4)
        assert perf.samples == 3

    def test_evaluate_uses_created_at_fallback(self):
        db = MagicMock()
        r1 = MagicMock(predicted_return=0.0, actual_return=0.0, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), prediction_date=datetime(2023, 1, 1, tzinfo=timezone.utc))
        db.query.return_value.filter.return_value.all.return_value = [r1]
        engine = SelfLearningEngine()
        perf = engine.evaluate_performance(db, "test_model")
        assert perf.last_updated.year == 2024


class TestShouldRetrain:
    def test_returns_false_when_samples_below_minimum(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        engine = SelfLearningEngine()
        assert engine.should_retrain(db, "test_model", min_samples=30, max_error=0.05) is False

    def test_returns_false_when_mae_acceptable(self):
        db = MagicMock()
        r = MagicMock(predicted_return=0.01, actual_return=0.0105, created_at=None, prediction_date=datetime.now(timezone.utc))
        db.query.return_value.filter.return_value.all.return_value = [r] * 30
        engine = SelfLearningEngine()
        assert engine.should_retrain(db, "test_model", min_samples=30, max_error=0.05) is False

    def test_returns_true_when_mae_exceeds_max_error(self):
        db = MagicMock()
        r = MagicMock(predicted_return=0.10, actual_return=-0.10, created_at=None, prediction_date=datetime.now(timezone.utc))
        db.query.return_value.filter.return_value.all.return_value = [r] * 30
        engine = SelfLearningEngine()
        assert engine.should_retrain(db, "test_model", min_samples=30, max_error=0.05) is True


class TestAutoRetrain:
    def test_skips_when_performance_acceptable(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        engine = SelfLearningEngine()
        result = engine.auto_retrain(db, "test_model")
        assert result["retrained"] is False
        assert "performance acceptable" in result["reason"]

    def test_raises_for_malformed_model_name(self):
        db = MagicMock()
        r = MagicMock(predicted_return=0.1, actual_return=-0.1, created_at=None, prediction_date=datetime.now(timezone.utc))
        db.query.return_value.filter.return_value.all.return_value = [r] * 30
        engine = SelfLearningEngine()
        result = engine.auto_retrain(db, "invalid_name")
        assert result["retrained"] is False


class TestCompareModels:
    def make_feedback(self, ticker="SBER", predicted=0.05, actual=0.03, features_hash="abc", date=None):
        r = MagicMock()
        r.ticker = ticker
        r.predicted_return = predicted
        r.actual_return = actual
        r.features_hash = features_hash
        r.created_at = date or datetime.now(timezone.utc)
        r.prediction_date = date or datetime.now(timezone.utc)
        return r

    def test_no_common_features_returns_insufficient(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.side_effect = [
            [self.make_feedback(features_hash="hash_a")],
            [self.make_feedback(features_hash="hash_b")],
        ]
        engine = SelfLearningEngine()
        result = engine.compare_models(db, "model_a", "model_b")
        assert "insufficient paired data" in result["conclusion"]

    def test_common_features_computes_mae_and_direction(self):
        db = MagicMock()
        common = [
            self.make_feedback(predicted=0.05, actual=0.04, features_hash="abc"),
            self.make_feedback(predicted=0.05, actual=0.04, features_hash="abc"),
        ]
        db.query.return_value.filter.return_value.all.side_effect = [common, common]
        engine = SelfLearningEngine()
        result = engine.compare_models(db, "model_a", "model_b")
        assert result["paired_samples"] > 0
        assert "model_a_mae" in result
        assert "model_b_mae" in result
        assert result["winner"] in ("model_a", "model_b", "tie")

    def test_winner_is_model_with_lower_mae_and_better_direction(self):
        db = MagicMock()
        feedback_a = [
            self.make_feedback(predicted=0.05, actual=0.049, features_hash="abc"),
            self.make_feedback(predicted=0.05, actual=0.049, features_hash="abc"),
        ]
        feedback_b = [
            self.make_feedback(predicted=0.05, actual=0.01, features_hash="abc"),
            self.make_feedback(predicted=0.05, actual=0.01, features_hash="abc"),
        ]
        db.query.return_value.filter.return_value.all.side_effect = [feedback_a, feedback_b]
        engine = SelfLearningEngine()
        result = engine.compare_models(db, "model_a", "model_b")
        assert result["winner"] == "model_a"


class TestFeaturesHash:
    def test_hash_is_deterministic(self):
        features = {"rsi": 45.0, "sma_20": 100.0, "volume": 5000}
        h1 = SelfLearningEngine.features_hash(features)
        h2 = SelfLearningEngine.features_hash(features)
        assert h1 == h2

    def test_different_features_produce_different_hashes(self):
        f1 = {"rsi": 45.0}
        f2 = {"rsi": 50.0}
        h1 = SelfLearningEngine.features_hash(f1)
        h2 = SelfLearningEngine.features_hash(f2)
        assert h1 != h2

    def test_hash_is_16_character_hex_string(self):
        features = {"rsi": 45.0, "sma_20": 100.0}
        h = SelfLearningEngine.features_hash(features)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)
