from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
import pytest

from src.analysis.attribution import NewsAttribution


@pytest.fixture
def mock_model():
    model = MagicMock()
    model._models = {}
    type(model).horizons = PropertyMock(return_value=[1, 3, 7])
    return model


@pytest.fixture
def attribution(mock_model):
    return NewsAttribution(mock_model)


class TestNewsAttributionInit:
    def test_stores_model(self, mock_model):
        na = NewsAttribution(mock_model)
        assert na._model is mock_model
        assert na._explainers == {}


class TestGetExplainer:
    def test_returns_cached_explainer(self, attribution):
        attribution._explainers[1] = "cached"
        result = attribution._get_explainer(1)
        assert result == "cached"

    def test_returns_none_when_model_missing(self, attribution):
        result = attribution._get_explainer(99)
        assert result is None

    def test_returns_none_when_shap_unavailable(self, attribution):
        attribution._model._models[1] = MagicMock()
        with patch("src.analysis.attribution.shap", None):
            result = attribution._get_explainer(1)
            assert result is None

    def test_creates_tree_explainer(self, attribution):
        xgb_model = MagicMock()
        attribution._model._models[1] = xgb_model
        fake_explainer = MagicMock()
        with patch("src.analysis.attribution.shap") as mock_shap:
            mock_shap.TreeExplainer.return_value = fake_explainer
            result = attribution._get_explainer(1)
            assert result == fake_explainer
            assert attribution._explainers[1] == fake_explainer
            mock_shap.TreeExplainer.assert_called_once_with(xgb_model)

    def test_returns_none_on_explainer_error(self, attribution):
        attribution._model._models[1] = MagicMock()
        with patch("src.analysis.attribution.shap") as mock_shap:
            mock_shap.TreeExplainer.side_effect = RuntimeError("fail")
            result = attribution._get_explainer(1)
            assert result is None


class TestExplain:
    def test_uses_shap_when_available(self, attribution):
        with (
            patch("src.analysis.attribution.shap") as mock_shap,
            patch("src.analysis.attribution.extract_features") as mock_extract,
            patch("src.analysis.attribution.ALL_FEATURE_COLS", ["f1", "f2"]),
            patch.object(attribution, "_get_explainer") as mock_get_exp,
        ):
            mock_extract.return_value = {"f1": 0.1, "f2": -0.2}
            mock_explainer = MagicMock()
            mock_explainer.shap_values.return_value = np.array([[0.5, -0.3]])
            mock_get_exp.return_value = mock_explainer

            result = attribution.explain(MagicMock(), MagicMock(), horizon_days=1)
            assert len(result) == 2
            assert result[0]["importance"] >= result[1]["importance"]

    def test_falls_back_to_coefficient_when_no_shap(self, attribution):
        with (
            patch("src.analysis.attribution.shap", None),
            patch("src.analysis.attribution.extract_features") as mock_extract,
            patch("src.analysis.attribution.ALL_FEATURE_COLS", ["f1", "f2"]),
            patch.object(attribution, "_get_explainer", return_value=None),
            patch.object(attribution, "_coefficient_attribution") as mock_coeff,
        ):
            mock_extract.return_value = {}
            mock_coeff.return_value = [{"feature": "f1", "importance": 0.1, "sign": "positive"}]
            result = attribution.explain(MagicMock(), MagicMock(), horizon_days=1)
            assert result == [{"feature": "f1", "importance": 0.1, "sign": "positive"}]

    def test_returns_sorted_by_importance_descending(self, attribution):
        with (
            patch("src.analysis.attribution.shap") as mock_shap,
            patch("src.analysis.attribution.extract_features") as mock_extract,
            patch("src.analysis.attribution.ALL_FEATURE_COLS", ["a", "b"]),
            patch.object(attribution, "_get_explainer") as mock_get_exp,
        ):
            mock_extract.return_value = {"a": 0.5, "b": -0.1}
            mock_explainer = MagicMock()
            mock_explainer.shap_values.return_value = np.array([[0.1, 0.5]])
            mock_get_exp.return_value = mock_explainer
            result = attribution.explain(MagicMock(), MagicMock(), horizon_days=1)
            assert result[0]["feature"] == "b"


class TestCoefficientAttribution:
    def test_returns_sorted_importances(self, attribution):
        xgb_model = MagicMock()
        xgb_model.feature_importances_ = np.array([0.1, 0.5, 0.2])
        attribution._model._models[1] = xgb_model
        with patch("src.analysis.attribution.ALL_FEATURE_COLS", ["a", "b", "c"]):
            result = attribution._coefficient_attribution(1)
            assert len(result) == 3
            assert result[0]["feature"] == "b"

    def test_returns_empty_when_model_missing(self, attribution):
        result = attribution._coefficient_attribution(99)
        assert result == []

    def test_loads_model_when_not_cached(self, attribution):
        xgb_model = MagicMock()
        xgb_model.feature_importances_ = np.array([0.3, 0.7])
        attribution._model.load.return_value = xgb_model
        with patch("src.analysis.attribution.ALL_FEATURE_COLS", ["a", "b"]):
            result = attribution._coefficient_attribution(1)
            assert len(result) == 2
            attribution._model.load.assert_called_once_with(1)

    def test_returns_empty_on_load_failure(self, attribution):
        attribution._model.load.side_effect = FileNotFoundError
        result = attribution._coefficient_attribution(1)
        assert result == []


class TestSummaryStats:
    def test_returns_empty_when_no_training_data(self, attribution):
        with patch("src.analysis.ml.news_impact_features.build_training_data") as mock_build:
            mock_build.return_value = MagicMock(empty=True)
            result = attribution.summary_stats(MagicMock(), "AAPL")
            assert result == {}

    def test_returns_empty_when_shap_unavailable_and_no_coefficient(self, attribution):
        with (
            patch("src.analysis.ml.news_impact_features.build_training_data") as mock_build,
            patch("src.analysis.attribution.shap", None),
            patch.object(attribution, "_coefficient_summary") as mock_coeff_summary,
        ):
            df = MagicMock()
            df.empty = False
            mock_build.return_value = df
            mock_coeff_summary.return_value = {}
            result = attribution.summary_stats(MagicMock(), "AAPL")
            assert result == {}


class TestCoefficientSummary:
    def test_returns_first_valid_horizon_importances(self, attribution):
        xgb_model = MagicMock()
        xgb_model.feature_importances_ = np.array([0.1, 0.9])
        attribution._model._models[1] = xgb_model
        with patch("src.analysis.attribution.ALL_FEATURE_COLS", ["a", "b"]):
            result = attribution._coefficient_summary()
            assert result == {"a": 0.1, "b": 0.9}

    def test_returns_empty_when_no_models(self, attribution):
        attribution._model.load.side_effect = FileNotFoundError
        result = attribution._coefficient_summary()
        assert result == {}
