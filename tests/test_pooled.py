from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
import pandas as pd
import pytest

from src.analysis.ml.pooled import PooledMLClassifier, _standardize


class TestStandardize:
    def test_basic_standardization(self):
        x = np.array([1.0, 3.0, 5.0])
        result = _standardize(x, mean=3.0, std=2.0)
        expected = (x - 3.0) / 2.0
        np.testing.assert_array_almost_equal(result, expected)

    def test_zero_std_returns_zeros(self):
        x = np.array([5.0, 5.0, 5.0])
        result = _standardize(x, mean=5.0, std=0.0)
        np.testing.assert_array_equal(result, [0.0, 0.0, 0.0])

    def test_mixed_values(self):
        x = np.array([0.0, 10.0])
        result = _standardize(x, mean=5.0, std=5.0)
        expected = np.array([-1.0, 1.0])
        np.testing.assert_array_almost_equal(result, expected)


class TestPooledMLClassifier:
    @pytest.fixture
    def mock_model(self):
        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.6, 0.4]])
        return model

    @pytest.fixture
    def mock_factory(self, mock_model):
        factory = MagicMock()
        factory.__name__ = "MockClassifier"
        instance = MagicMock()
        instance._create_model.return_value = mock_model
        factory.return_value = instance
        return factory

    @pytest.fixture
    def classifier(self, mock_factory):
        return PooledMLClassifier(base_model_factory=mock_factory, ticker="AAPL")

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=10), "close": range(100, 110)}
        )

    # ── _get_ticker_id ─────────────────────────────────────────────────────

    def test_get_ticker_id_returns_zero_for_unknown(self, classifier):
        assert classifier._get_ticker_id("UNKNOWN") == 0

    def test_get_ticker_id_returns_mapped_value(self, classifier):
        classifier._ticker_map = {"AAPL": 0, "MSFT": 1}
        assert classifier._get_ticker_id("MSFT") == 1

    # ── _drop_abs ───────────────────────────────────────────────────────────

    def test_drop_abs_removes_absolute_features(self, classifier):
        fp = pd.DataFrame({"close": [1], "sma_20": [2], "rsi": [50], "other": [10]})
        result = classifier._drop_abs(fp)
        assert "close" not in result.columns
        assert "sma_20" not in result.columns
        assert "rsi" in result.columns
        assert "other" in result.columns

    def test_drop_abs_handles_missing_columns(self, classifier):
        fp = pd.DataFrame({"rsi": [50]})
        result = classifier._drop_abs(fp)
        assert "rsi" in result.columns

    # ── train_pooled ────────────────────────────────────────────────────────

    @patch("src.analysis.ml.pooled.compute_threshold")
    @patch("src.analysis.ml.pooled.build_labels")
    @patch("src.analysis.ml.pooled.prepare_features")
    @patch("src.analysis.ml.pooled.enrich_macro")
    @patch("src.analysis.ml.pooled.TechnicalAnalyzer")
    def test_train_pooled_returns_false_on_empty_data(
        self, mock_tech, mock_macro, mock_prep, mock_labels, mock_thresh, classifier
    ):
        assert classifier.train_pooled({}) is False

    @patch("src.analysis.ml.pooled.compute_threshold")
    @patch("src.analysis.ml.pooled.build_labels")
    @patch("src.analysis.ml.pooled.prepare_features")
    @patch("src.analysis.ml.pooled.enrich_macro")
    @patch("src.analysis.ml.pooled.TechnicalAnalyzer")
    def test_train_pooled_success(
        self, mock_tech_cls, mock_macro, mock_prep, mock_labels, mock_thresh, classifier, mock_factory, mock_model
    ):
        mock_tech = MagicMock()
        mock_tech.compute_all.return_value = pd.DataFrame(
            {"close": range(100, 200), "rsi": 50, "macd_hist": 0, "sma_20": 110, "sma_50": 105, "date": pd.date_range("2024-01-01", periods=100)}
        )
        mock_tech_cls.return_value = mock_tech
        mock_macro.side_effect = lambda df: df
        mock_prep.return_value = pd.DataFrame(
            {"rsi": np.random.rand(100), "macd_hist": np.random.rand(100), "sma_20": np.random.rand(100),
             "sma_50": np.random.rand(100), "ticker_id": 0}
        )
        mock_thresh.return_value = 0.03
        mock_labels.return_value = (
            np.array([1, 0] * 30 + [np.nan] * 40),
            np.array([True] * 60 + [False] * 40),
        )

        result = classifier.train_pooled({"AAPL": pd.DataFrame({"close": range(100, 200), "date": pd.date_range("2024-01-01", periods=100)})})
        assert result is True
        assert classifier._model is mock_model
        assert "AAPL" in classifier._ticker_map
        mock_model.fit.assert_called_once()

    @patch("src.analysis.ml.pooled.compute_threshold")
    @patch("src.analysis.ml.pooled.build_labels")
    @patch("src.analysis.ml.pooled.prepare_features")
    @patch("src.analysis.ml.pooled.enrich_macro")
    @patch("src.analysis.ml.pooled.TechnicalAnalyzer")
    def test_train_pooled_returns_false_when_features_empty(
        self, mock_tech_cls, mock_macro, mock_prep, mock_labels, mock_thresh, classifier
    ):
        mock_tech = MagicMock()
        mock_tech.compute_all.return_value = pd.DataFrame({"close": [100]})
        mock_tech_cls.return_value = mock_tech
        mock_macro.side_effect = lambda df: df
        mock_prep.return_value = pd.DataFrame()
        result = classifier.train_pooled({"AAPL": pd.DataFrame({"close": [100]})})
        assert result is False

    @patch("src.analysis.ml.pooled.compute_threshold")
    @patch("src.analysis.ml.pooled.build_labels")
    @patch("src.analysis.ml.pooled.prepare_features")
    @patch("src.analysis.ml.pooled.enrich_macro")
    @patch("src.analysis.ml.pooled.TechnicalAnalyzer")
    def test_train_pooled_returns_false_when_mask_sum_lt_5(
        self, mock_tech_cls, mock_macro, mock_prep, mock_labels, mock_thresh, classifier
    ):
        mock_tech = MagicMock()
        mock_tech.compute_all.return_value = pd.DataFrame(
            {"close": range(100, 130), "rsi": 50, "macd_hist": 0, "sma_20": 110, "sma_50": 105, "date": pd.date_range("2024-01-01", periods=30)}
        )
        mock_tech_cls.return_value = mock_tech
        mock_macro.side_effect = lambda df: df
        mock_prep.return_value = pd.DataFrame(
            {"rsi": np.random.rand(30), "macd_hist": np.random.rand(30), "sma_20": np.random.rand(30),
             "sma_50": np.random.rand(30), "ticker_id": 0}
        )
        mock_thresh.return_value = 0.03
        mock_labels.return_value = (
            np.zeros(30),
            np.array([False] * 30),
        )
        result = classifier.train_pooled({"AAPL": pd.DataFrame({"close": range(100, 130), "date": pd.date_range("2024-01-01", periods=30)})})
        assert result is False

    # ── predict ─────────────────────────────────────────────────────────────

    def test_predict_returns_fallback_when_no_model(self, classifier, sample_df):
        result = classifier.predict(sample_df)
        assert result["action"] == "NEUTRAL"
        assert result["confidence"] == 0.0

    def test_predict_returns_fallback_when_empty_df(self, classifier):
        result = classifier.predict(pd.DataFrame())
        assert result["action"] == "NEUTRAL"

    def test_predict_returns_fallback_when_no_date_column(self, classifier):
        df = pd.DataFrame({"close": [100]})
        result = classifier.predict(df)
        assert result["action"] == "NEUTRAL"

    @patch("src.analysis.ml.pooled.TechnicalAnalyzer")
    @patch("src.analysis.ml.pooled.enrich_macro")
    @patch("src.analysis.ml.pooled.prepare_features")
    def test_predict_with_model(
        self, mock_prep, mock_macro, mock_tech_cls, classifier, sample_df, mock_model
    ):
        classifier._model = mock_model
        classifier._ticker_map = {"AAPL": 0}

        mock_tech = MagicMock()
        mock_tech.compute_all.return_value = sample_df
        mock_tech_cls.return_value = mock_tech
        mock_macro.side_effect = lambda df: df
        mock_prep.return_value = pd.DataFrame(
            {"rsi": [50], "macd_hist": [0.1], "sma_20": [105], "sma_50": [102], "ticker_id": [0]}
        )

        result = classifier.predict(sample_df)
        assert "action" in result
        assert "confidence" in result
        assert "signal_score" in result
        assert "probability" in result
        assert 0.0 <= result["confidence"] <= 1.0

    @patch("src.analysis.ml.pooled.TechnicalAnalyzer")
    @patch("src.analysis.ml.pooled.enrich_macro")
    @patch("src.analysis.ml.pooled.prepare_features")
    def test_predict_fallback_when_features_empty(
        self, mock_prep, mock_macro, mock_tech_cls, classifier, sample_df, mock_model
    ):
        classifier._model = mock_model
        classifier._ticker_map = {"AAPL": 0}

        mock_tech = MagicMock()
        mock_tech.compute_all.return_value = sample_df
        mock_tech_cls.return_value = mock_tech
        mock_macro.side_effect = lambda df: df
        mock_prep.return_value = pd.DataFrame()

        result = classifier.predict(sample_df)
        assert result["action"] == "NEUTRAL"

    @patch("src.analysis.ml.pooled.TechnicalAnalyzer")
    @patch("src.analysis.ml.pooled.enrich_macro")
    @patch("src.analysis.ml.pooled.prepare_features")
    def test_predict_proba_failure_returns_fallback(
        self, mock_prep, mock_macro, mock_tech_cls, classifier, sample_df, mock_model
    ):
        mock_model.predict_proba.side_effect = RuntimeError("predict_proba failed")
        classifier._model = mock_model
        classifier._ticker_map = {"AAPL": 0}

        mock_tech = MagicMock()
        mock_tech.compute_all.return_value = sample_df
        mock_tech_cls.return_value = mock_tech
        mock_macro.side_effect = lambda df: df
        mock_prep.return_value = pd.DataFrame(
            {"rsi": [50], "macd_hist": [0.1], "sma_20": [105], "sma_50": [102], "ticker_id": [0]}
        )

        result = classifier.predict(sample_df)
        assert result["action"] == "NEUTRAL"

    @patch("src.analysis.ml.pooled.settings")
    @patch("src.analysis.ml.pooled.TechnicalAnalyzer")
    @patch("src.analysis.ml.pooled.enrich_macro")
    @patch("src.analysis.ml.pooled.prepare_features")
    def test_predict_action_threshold(
        self, mock_prep, mock_macro, mock_tech_cls, mock_settings, classifier, sample_df, mock_model
    ):
        mock_settings.ml_action_threshold = 0.55
        classifier._model = mock_model
        classifier._ticker_map = {"AAPL": 0}

        mock_tech = MagicMock()
        mock_tech.compute_all.return_value = sample_df
        mock_tech_cls.return_value = mock_tech
        mock_macro.side_effect = lambda df: df
        mock_prep.return_value = pd.DataFrame(
            {"rsi": [50], "macd_hist": [0.1], "sma_20": [105], "sma_50": [102], "ticker_id": [0]}
        )

        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        result = classifier.predict(sample_df)
        assert result["action"] in ("BUY", "SELL", "HOLD")

    def test_standardize_import(self):
        assert callable(_standardize)
