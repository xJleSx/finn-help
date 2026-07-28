from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.analysis.anomaly.autoencoder import AutoencoderAnomalyDetector
from src.analysis.ml.news_impact_features import ALL_FEATURE_COLS


@pytest.fixture
def mock_build_training_data():
    n = 30
    rng = np.random.default_rng(42)
    data = {}
    for col in ALL_FEATURE_COLS:
        if col in ("sentiment_positive", "sentiment_negative"):
            data[col] = rng.integers(0, 2, n).astype(np.float64)
        else:
            data[col] = rng.random(n).astype(np.float64)
    df = __import__("pandas").DataFrame(data)
    with patch("src.analysis.anomaly.autoencoder.build_training_data", return_value=df):
        yield


@pytest.fixture
def mock_build_anomaly_feature_vector():
    vec = np.array(
        [float(i % 3) / 3.0 for i in range(len(ALL_FEATURE_COLS))],
        dtype=np.float32,
    )
    with patch(
        "src.analysis.anomaly.features.build_anomaly_feature_vector",
        return_value=vec,
    ):
        yield


class TestAutoencoderAnomalyDetectorInit:
    def test_init_default_input_dim(self):
        d = AutoencoderAnomalyDetector()
        assert d.input_dim == len(ALL_FEATURE_COLS)
        assert d._model is None
        assert d._threshold == 0.0
        assert not d._trained

    def test_init_custom_input_dim(self):
        d = AutoencoderAnomalyDetector(input_dim=10)
        assert d.input_dim == 10

    def test_trained_property_default(self):
        d = AutoencoderAnomalyDetector()
        assert not d.trained


class TestAutoencoderAnomalyDetectorPredict:
    def test_predict_no_model_returns_zero(self):
        d = AutoencoderAnomalyDetector(input_dim=5)
        features = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        score = d.predict(features)
        assert score == 0.0

    def test_predict_article_no_model_returns_zero(self, mock_build_anomaly_feature_vector):
        d = AutoencoderAnomalyDetector(input_dim=24)
        mock_article = MagicMock()
        score = d.predict_article(MagicMock(), mock_article)
        assert score == 0.0

    def test_predict_article_truncates_when_vec_too_long(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector(input_dim=24)
        d.train(MagicMock(), "TEST")
        d._threshold = 0.5
        vec = np.array([0.1] * 30, dtype=np.float32)
        with patch("src.analysis.anomaly.features.build_anomaly_feature_vector", return_value=vec):
            score = d.predict_article(MagicMock(), MagicMock())
            assert 0.0 <= score <= 1.0

    def test_predict_article_pads_when_vec_too_short(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector(input_dim=24)
        d.train(MagicMock(), "TEST")
        d._threshold = 0.5
        vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        with patch("src.analysis.anomaly.features.build_anomaly_feature_vector", return_value=vec):
            score = d.predict_article(MagicMock(), MagicMock())
            assert 0.0 <= score <= 1.0

    def test_predict_returns_low_score_for_identical_input(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector(input_dim=24)
        d.train(MagicMock(), "TEST")
        features = np.zeros(len(ALL_FEATURE_COLS), dtype=np.float32)
        score = d.predict(features)
        assert 0.0 <= score <= 1.0

    def test_predict_returns_higher_score_for_outlier(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector(input_dim=24)
        d.train(MagicMock(), "TEST")
        normal = np.zeros(len(ALL_FEATURE_COLS), dtype=np.float32)
        outlier = np.ones(len(ALL_FEATURE_COLS), dtype=np.float32) * 100.0
        normal_score = d.predict(normal)
        outlier_score = d.predict(outlier)
        assert outlier_score >= normal_score

    def test_predict_clamps_above_one(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector(input_dim=24)
        d.train(MagicMock(), "TEST")
        d._threshold = 0.001
        extreme = np.ones(len(ALL_FEATURE_COLS), dtype=np.float32) * 1e6
        score = d.predict(extreme)
        assert score == 1.0


class TestAutoencoderAnomalyDetectorTrain:
    def test_train_no_ticker(self):
        d = AutoencoderAnomalyDetector()
        result = d.train(MagicMock())
        assert not result["trained"]
        assert result["reason"] == "no ticker"

    def test_train_insufficient_data(self):
        with patch("src.analysis.anomaly.autoencoder.build_training_data") as mock_btd:
            mock_btd.return_value = __import__("pandas").DataFrame()
            d = AutoencoderAnomalyDetector()
            result = d.train(MagicMock(), "TEST")
            assert not result["trained"]
            assert result["reason"] == "insufficient data"

    def test_train_empty_df(self):
        with patch("src.analysis.anomaly.autoencoder.build_training_data") as mock_btd:
            mock_btd.return_value = __import__("pandas").DataFrame({"a": []})
            d = AutoencoderAnomalyDetector()
            result = d.train(MagicMock(), "TEST")
            assert not result["trained"]
            assert result["reason"] == "insufficient data"

    def test_train_success(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector()
        result = d.train(MagicMock(), "TEST")
        assert result["trained"]
        assert result["samples"] == 30
        assert result["features"] == len(ALL_FEATURE_COLS)
        assert result["threshold"] > 0
        assert result["final_loss"] >= 0
        assert d._model is not None
        assert d.trained

    def test_train_updates_input_dim_when_some_features_missing(self):
        n = 30
        rng = np.random.default_rng(42)
        subset_cols = ALL_FEATURE_COLS[:10]
        data = {c: rng.random(n).astype(np.float64) for c in subset_cols}
        df = __import__("pandas").DataFrame(data)
        with patch("src.analysis.anomaly.autoencoder.build_training_data", return_value=df):
            d = AutoencoderAnomalyDetector(input_dim=len(ALL_FEATURE_COLS))
            result = d.train(MagicMock(), "TEST")
            assert result["trained"]
            assert result["features"] == 10
            assert d.input_dim == 10

    def test_train_accumulates_losses(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector()
        d.train(MagicMock(), "TEST")
        assert len(d._losses) > 0
        assert all(isinstance(l, float) for l in d._losses)

    def test_train_sets_threshold_from_percentile(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector()
        d.train(MagicMock(), "TEST")
        assert d._threshold > 0.0

    def test_predict_after_training(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector()
        d.train(MagicMock(), "TEST")
        features = np.array(
            [float(i % 3) / 3.0 for i in range(len(ALL_FEATURE_COLS))],
            dtype=np.float32,
        )
        score = d.predict(features)
        assert 0.0 <= score <= 1.0


class TestAutoencoderAnomalyDetectorPredictArticleIntegration:
    def test_predict_article_after_training(self, mock_build_training_data, mock_build_anomaly_feature_vector):
        d = AutoencoderAnomalyDetector()
        d.train(MagicMock(), "TEST")
        score = d.predict_article(MagicMock(), MagicMock())
        assert 0.0 <= score <= 1.0

    def test_double_train_retrains(self, mock_build_training_data):
        d = AutoencoderAnomalyDetector()
        r1 = d.train(MagicMock(), "TEST")
        assert r1["trained"]
        r2 = d.train(MagicMock(), "TEST")
        assert r2["trained"]
        assert r2["samples"] == 30
