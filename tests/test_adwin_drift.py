from __future__ import annotations

import numpy as np
import pytest
from sklearn.datasets import make_classification

from src.analysis.ml.drift.adwin import ADWINDetector
from src.analysis.ml.drift.incremental import ConceptDriftPipeline, IncrementalTrainer
from src.model_registry import set_model_dir


@pytest.fixture(autouse=True)
def _temp_model_dir(tmp_path):
    set_model_dir(str(tmp_path / "models"))
    yield


class TestADWINDetector:
    def test_detects_drift_on_mean_shift(self):
        detector = ADWINDetector(delta=0.05)
        rng = np.random.default_rng(42)
        for _ in range(100):
            detector.add_element(float(rng.normal(0, 0.5)))
        assert detector.get_width() > 0
        drifted = False
        for _ in range(50):
            v = float(rng.normal(2, 0.5))
            if detector.add_element(v):
                drifted = True
                break
        assert drifted, "ADWIN should detect mean shift from 0 to 2"

    def test_no_drift_on_stable_data(self):
        detector = ADWINDetector(delta=0.05)
        rng = np.random.default_rng(42)
        drifted = False
        for _ in range(300):
            if detector.add_element(float(rng.normal(0, 0.5))):
                drifted = True
                break
        assert not drifted, "ADWIN should not detect drift on stable data"

    def test_get_width_and_mean(self):
        detector = ADWINDetector()
        assert detector.get_width() == 0
        assert detector.get_mean() == 0.0
        detector.add_element(1.0)
        detector.add_element(2.0)
        assert detector.get_width() == 2
        assert detector.get_mean() == 1.5

    def test_reset(self):
        detector = ADWINDetector()
        detector.add_element(1.0)
        detector.reset()
        assert detector.get_width() == 0
        assert detector.get_mean() == 0.0

    def test_detect_batch_returns_indices(self):
        detector = ADWINDetector(delta=0.05)
        rng = np.random.default_rng(42)
        stable = list(rng.normal(0, 0.5, 100))
        shift = list(rng.normal(2, 0.5, 50))
        indices = detector.detect_batch(stable + shift)
        assert isinstance(indices, list)
        assert len(indices) > 0


class TestIncrementalTrainer:
    def test_partial_fit_xgboost(self):
        pytest.importorskip("xgboost")
        import xgboost as xgb

        X, y = make_classification(n_samples=200, n_features=5, random_state=42)
        model = xgb.XGBClassifier(n_estimators=10, max_depth=2, verbosity=0)
        model.fit(X[:100], y[:100])

        trainer = IncrementalTrainer()
        trainer.partial_fit(model, X[100:], y[100:], feature_names=[f"f{i}" for i in range(5)])
        preds = model.predict(X[100:])
        assert preds.shape[0] == 100

    def test_partial_fit_lightgbm(self):
        pytest.importorskip("lightgbm")
        import lightgbm as lgb

        X, y = make_classification(n_samples=200, n_features=5, random_state=42)
        model = lgb.LGBMClassifier(n_estimators=10, max_depth=2, verbosity=-1)
        model.fit(X[:100], y[:100])

        trainer = IncrementalTrainer()
        trainer.partial_fit(model, X[100:], y[100:], feature_names=[f"f{i}" for i in range(5)])
        preds = model.predict(X[100:])
        assert preds.shape[0] == 100

    def test_evaluate_returns_metrics(self):
        pytest.importorskip("xgboost")
        import xgboost as xgb

        X, y = make_classification(n_samples=100, n_features=5, random_state=42)
        X_train, X_test, y_train, y_test = X[:80], X[80:], y[:80], y[80:]
        model = xgb.XGBClassifier(n_estimators=10, max_depth=2, verbosity=0)
        model.fit(X_train, y_train)

        trainer = IncrementalTrainer()
        metrics = trainer.evaluate(model, X_test, y_test)
        assert "accuracy" in metrics
        assert "precision" in metrics
        assert "recall" in metrics
        assert "f1" in metrics
        assert all(0.0 <= v <= 1.0 for v in metrics.values())


class TestConceptDriftPipeline:
    def test_process_batch_integration(self):
        pytest.importorskip("xgboost")
        import xgboost as xgb

        X, y = make_classification(n_samples=300, n_features=5, random_state=42)
        model = xgb.XGBClassifier(n_estimators=10, max_depth=2, verbosity=0)
        model.fit(X[:100], y[:100])

        detector = ADWINDetector(delta=0.1)
        pipeline = ConceptDriftPipeline(model=model, detector=detector, model_name="test_drift")

        for i in range(3):
            start = 100 + i * 60
            end = start + 60
            result = pipeline.process_batch(
                X[start:end], y[start:end], feature_names=[f"f{j}" for j in range(5)]
            )
            assert "drift_detected" in result
            assert "metrics" in result
            assert "accuracy" in result["metrics"]
            assert result["batch"] == i + 1

    def test_pipeline_tracks_drift_events(self):
        pytest.importorskip("lightgbm")
        import lightgbm as lgb

        X, y = make_classification(n_samples=400, n_features=5, random_state=42)
        model = lgb.LGBMClassifier(n_estimators=10, max_depth=2, verbosity=-1)
        model.fit(X[:100], y[:100])

        pipeline = ConceptDriftPipeline(model=model)
        for i in range(5):
            start = 100 + i * 60
            end = start + 60
            pipeline.process_batch(X[start:end], y[start:end])

        assert pipeline.retrain_count >= 0
        assert pipeline._batch_counter == 5
