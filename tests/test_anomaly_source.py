from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analysis.anomaly.source_anomaly import SourceAnomalyDetector


class TestSourceAnomalyDetectorInit:
    def test_init(self):
        d = SourceAnomalyDetector()
        assert d._freqs == {}
        assert not d._trained

    def test_trained_property_default(self):
        d = SourceAnomalyDetector()
        assert not d.trained


class TestSourceAnomalyDetectorTrain:
    def test_train_stores_frequencies(self):
        mock_freqs = {"SourceA": {"MACRO": 1.5, "COMPANY": 0.8}}
        with patch(
            "src.analysis.anomaly.source_anomaly.source_frequencies",
            return_value=mock_freqs,
        ) as mock_sf:
            d = SourceAnomalyDetector()
            result = d.train(MagicMock())
            mock_sf.assert_called_once()
            assert result["trained"]
            assert result["sources"] == 1
            assert d._freqs == mock_freqs
            assert d.trained

    def test_train_with_multiple_sources(self):
        mock_freqs = {
            "SourceA": {"MACRO": 1.0},
            "SourceB": {"COMPANY": 2.0},
            "SourceC": {"MACRO": 0.5, "SECTOR": 3.0},
        }
        with patch(
            "src.analysis.anomaly.source_anomaly.source_frequencies",
            return_value=mock_freqs,
        ):
            d = SourceAnomalyDetector()
            result = d.train(MagicMock())
            assert result["sources"] == 3

    def test_train_empty_frequencies(self):
        with patch(
            "src.analysis.anomaly.source_anomaly.source_frequencies",
            return_value={},
        ):
            d = SourceAnomalyDetector()
            result = d.train(MagicMock())
            assert result["trained"]
            assert result["sources"] == 0
            assert d.trained


class TestSourceAnomalyDetectorPredictArticle:
    def test_predict_not_trained_returns_zero(self):
        d = SourceAnomalyDetector()
        score = d.predict_article(MagicMock())
        assert score == 0.0

    def test_predict_unknown_source_returns_zero(self):
        d = SourceAnomalyDetector()
        d._freqs = {"KnownSource": {"MACRO": 2.0}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.source_name = "UnknownSource"
        mock_article.category = "MACRO"
        score = d.predict_article(mock_article)
        assert score == 0.0

    def test_predict_ratio_leq_01_returns_08(self):
        d = SourceAnomalyDetector()
        d._freqs = {"SourceA": {"MACRO": 0.05}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.source_name = "SourceA"
        mock_article.category = "MACRO"
        score = d.predict_article(mock_article)
        assert score == 0.8

    def test_predict_ratio_leq_03_returns_04(self):
        d = SourceAnomalyDetector()
        d._freqs = {"SourceA": {"MACRO": 0.2}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.source_name = "SourceA"
        mock_article.category = "MACRO"
        score = d.predict_article(mock_article)
        assert score == 0.4

    def test_predict_ratio_between_03_and_50_returns_00(self):
        d = SourceAnomalyDetector()
        d._freqs = {"SourceA": {"MACRO": 1.0}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.source_name = "SourceA"
        mock_article.category = "MACRO"
        score = d.predict_article(mock_article)
        assert score == 0.0

    def test_predict_ratio_geq_50_returns_00(self):
        d = SourceAnomalyDetector()
        d._freqs = {"SourceA": {"MACRO": 10.0}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.source_name = "SourceA"
        mock_article.category = "MACRO"
        score = d.predict_article(mock_article)
        assert score == 0.0

    def test_predict_article_handles_null_source_name(self):
        d = SourceAnomalyDetector()
        d._freqs = {"unknown": {"MACRO": 0.05}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.source_name = None
        mock_article.category = "MACRO"
        score = d.predict_article(mock_article)
        assert score == 0.8

    def test_predict_article_handles_null_category(self):
        d = SourceAnomalyDetector()
        d._freqs = {"SourceA": {"UNCLASSIFIED": 0.05}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.source_name = "SourceA"
        mock_article.category = None
        score = d.predict_article(mock_article)
        assert score == 0.8

    def test_predict_uses_article_attributes_directly(self):
        d = SourceAnomalyDetector()
        d._freqs = {"RareSource": {"SECTOR": 0.05}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.source_name = "RareSource"
        mock_article.category = "SECTOR"
        score = d.predict_article(mock_article)
        assert score == 0.8
