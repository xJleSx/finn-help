from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analysis.anomaly.topic_anomaly import TopicAnomalyDetector


class TestTopicAnomalyDetectorInit:
    def test_init(self):
        d = TopicAnomalyDetector()
        assert d._freqs == {}
        assert not d._trained

    def test_trained_property_default(self):
        d = TopicAnomalyDetector()
        assert not d.trained


class TestTopicAnomalyDetectorTrain:
    def test_train_stores_frequencies(self):
        mock_freqs = {
            "AAPL": {("MACRO", "monetary_policy"): 10, ("COMPANY", "earnings"): 5},
        }
        with patch(
            "src.analysis.anomaly.topic_anomaly.topic_frequencies",
            return_value=mock_freqs,
        ) as mock_tf:
            d = TopicAnomalyDetector()
            result = d.train(MagicMock())
            mock_tf.assert_called_once()
            assert result["trained"]
            assert result["tickers"] == 1
            assert result["topics"] == 2
            assert d._freqs == mock_freqs
            assert d.trained

    def test_train_multiple_tickers(self):
        mock_freqs = {
            "AAPL": {("MACRO", "monetary_policy"): 10},
            "MSFT": {("COMPANY", "earnings"): 5},
            "GOOG": {("MACRO", "inflation"): 3},
        }
        with patch(
            "src.analysis.anomaly.topic_anomaly.topic_frequencies",
            return_value=mock_freqs,
        ):
            d = TopicAnomalyDetector()
            result = d.train(MagicMock())
            assert result["tickers"] == 3
            assert result["topics"] == 3

    def test_train_empty_frequencies(self):
        with patch(
            "src.analysis.anomaly.topic_anomaly.topic_frequencies",
            return_value={},
        ):
            d = TopicAnomalyDetector()
            result = d.train(MagicMock())
            assert result["trained"]
            assert result["tickers"] == 0
            assert result["topics"] == 0


class TestTopicAnomalyDetectorPredictArticle:
    def test_predict_not_trained_returns_zero(self):
        d = TopicAnomalyDetector()
        score = d.predict_article(MagicMock())
        assert score == 0.0

    def test_predict_unknown_ticker_returns_zero(self):
        d = TopicAnomalyDetector()
        d._freqs = {"AAPL": {("MACRO", "monetary_policy"): 10}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.ticker = "UNKNOWN"
        mock_article.category = "MACRO"
        mock_article.subcategory = "monetary_policy"
        score = d.predict_article(mock_article)
        assert score == 0.0

    def test_predict_total_below_min_freq_returns_zero(self):
        d = TopicAnomalyDetector()
        d._freqs = {"AAPL": {("MACRO", "monetary_policy"): 1}}
        d._trained = True
        mock_article = MagicMock()
        mock_article.ticker = "AAPL"
        mock_article.category = "MACRO"
        mock_article.subcategory = "monetary_policy"
        with patch("src.analysis.anomaly.topic_anomaly.settings") as mock_settings:
            mock_settings.ml_anomaly_source_min_freq = 5
            score = d.predict_article(mock_article)
            assert score == 0.0

    def test_predict_zero_topic_count_returns_07(self):
        d = TopicAnomalyDetector()
        d._freqs = {
            "AAPL": {
                ("MACRO", "monetary_policy"): 100,
                ("COMPANY", "earnings"): 50,
            }
        }
        d._trained = True
        mock_article = MagicMock()
        mock_article.ticker = "AAPL"
        mock_article.category = "SECTOR"
        mock_article.subcategory = "energy"
        with patch("src.analysis.anomaly.topic_anomaly.settings") as mock_settings:
            mock_settings.ml_anomaly_source_min_freq = 3
            score = d.predict_article(mock_article)
            assert score == 0.7

    def test_predict_ratio_below_001_returns_05(self):
        d = TopicAnomalyDetector()
        d._freqs = {
            "AAPL": {
                ("MACRO", "monetary_policy"): 1000,
                ("COMPANY", "earnings"): 50,
                ("SECTOR", "energy"): 1,
            }
        }
        d._trained = True
        mock_article = MagicMock()
        mock_article.ticker = "AAPL"
        mock_article.category = "SECTOR"
        mock_article.subcategory = "energy"
        with patch("src.analysis.anomaly.topic_anomaly.settings") as mock_settings:
            mock_settings.ml_anomaly_source_min_freq = 3
            score = d.predict_article(mock_article)
            assert score == 0.5

    def test_predict_ratio_between_001_and_005_returns_02(self):
        d = TopicAnomalyDetector()
        d._freqs = {
            "AAPL": {
                ("MACRO", "monetary_policy"): 100,
                ("COMPANY", "earnings"): 50,
                ("SECTOR", "energy"): 5,
            }
        }
        d._trained = True
        total = 100 + 50 + 5
        ratio = 5 / total
        assert 0.01 <= ratio < 0.05
        mock_article = MagicMock()
        mock_article.ticker = "AAPL"
        mock_article.category = "SECTOR"
        mock_article.subcategory = "energy"
        with patch("src.analysis.anomaly.topic_anomaly.settings") as mock_settings:
            mock_settings.ml_anomaly_source_min_freq = 3
            score = d.predict_article(mock_article)
            assert score == 0.2

    def test_predict_ratio_geq_005_returns_00(self):
        d = TopicAnomalyDetector()
        d._freqs = {
            "AAPL": {
                ("MACRO", "monetary_policy"): 100,
                ("COMPANY", "earnings"): 50,
            }
        }
        d._trained = True
        mock_article = MagicMock()
        mock_article.ticker = "AAPL"
        mock_article.category = "MACRO"
        mock_article.subcategory = "monetary_policy"
        with patch("src.analysis.anomaly.topic_anomaly.settings") as mock_settings:
            mock_settings.ml_anomaly_source_min_freq = 3
            score = d.predict_article(mock_article)
            assert score == 0.0

    def test_predict_handles_null_category(self):
        d = TopicAnomalyDetector()
        d._freqs = {
            "AAPL": {("UNCLASSIFIED", "GENERAL"): 100},
        }
        d._trained = True
        mock_article = MagicMock()
        mock_article.ticker = "AAPL"
        mock_article.category = None
        mock_article.subcategory = None
        with patch("src.analysis.anomaly.topic_anomaly.settings") as mock_settings:
            mock_settings.ml_anomaly_source_min_freq = 3
            score = d.predict_article(mock_article)
            assert score in (0.0, 0.7, 0.5, 0.2)

    def test_predict_handles_empty_subcategory(self):
        d = TopicAnomalyDetector()
        d._freqs = {
            "AAPL": {("MACRO", "GENERAL"): 100},
        }
        d._trained = True
        mock_article = MagicMock()
        mock_article.ticker = "AAPL"
        mock_article.category = "MACRO"
        mock_article.subcategory = None
        with patch("src.analysis.anomaly.topic_anomaly.settings") as mock_settings:
            mock_settings.ml_anomaly_source_min_freq = 3
            score = d.predict_article(mock_article)
            assert score == 0.0
