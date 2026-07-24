from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session


@pytest.fixture
def mock_sub_detectors():
    with patch.multiple(
        "src.analysis.anomaly.detector",
        VolumeAnomalyDetector=MagicMock,
        SentimentAnomalyDetector=MagicMock,
        SourceAnomalyDetector=MagicMock,
        TopicAnomalyDetector=MagicMock,
        AutoencoderAnomalyDetector=MagicMock,
    ) as mocks:
        yield mocks


class TestAnomalyDetectorInit:
    def test_init_creates_sub_detectors(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        with patch("src.analysis.anomaly.detector.VolumeAnomalyDetector") as mock_v:
            with patch("src.analysis.anomaly.detector.SentimentAnomalyDetector") as mock_se:
                with patch("src.analysis.anomaly.detector.SourceAnomalyDetector") as mock_so:
                    with patch("src.analysis.anomaly.detector.TopicAnomalyDetector") as mock_t:
                        with patch("src.analysis.anomaly.detector.AutoencoderAnomalyDetector") as mock_a:
                            d = AnomalyDetector("TEST")
                            assert d.ticker == "TEST"
                            mock_v.assert_called_once_with("TEST")
                            mock_se.assert_called_once_with("TEST")
                            mock_so.assert_called_once_with()
                            mock_t.assert_called_once_with()
                            mock_a.assert_called_once_with()
                            assert d.volume is mock_v.return_value
                            assert d.sentiment is mock_se.return_value
                            assert d.source is mock_so.return_value
                            assert d.topic is mock_t.return_value
                            assert d.autoencoder is mock_a.return_value

    def test_init_default_ticker(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        with patch("src.analysis.anomaly.detector.VolumeAnomalyDetector") as mock_v:
            with patch("src.analysis.anomaly.detector.SentimentAnomalyDetector") as mock_se:
                with patch("src.analysis.anomaly.detector.SourceAnomalyDetector"):
                    with patch("src.analysis.anomaly.detector.TopicAnomalyDetector"):
                        with patch("src.analysis.anomaly.detector.AutoencoderAnomalyDetector"):
                            d = AnomalyDetector()
                            assert d.ticker == ""
                            mock_v.assert_called_once_with("")
                            mock_se.assert_called_once_with("")


class TestAnomalyDetectorTrainAll:
    def test_train_all_calls_all_sub_detectors(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_sentiment = MagicMock()
        mock_source = MagicMock()
        mock_topic = MagicMock()
        mock_autoencoder = MagicMock()
        mock_volume.train.return_value = {"trained": True}
        mock_sentiment.train.return_value = {"trained": True}
        mock_source.train.return_value = {"trained": True}
        mock_topic.train.return_value = {"trained": True}
        mock_autoencoder.train.return_value = {"trained": True}

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.ticker = "TEST"
        d.volume = mock_volume
        d.sentiment = mock_sentiment
        d.source = mock_source
        d.topic = mock_topic
        d.autoencoder = mock_autoencoder

        result = d.train_all(MagicMock())
        mock_volume.train.assert_called_once()
        mock_sentiment.train.assert_called_once()
        mock_source.train.assert_called_once()
        mock_topic.train.assert_called_once()
        mock_autoencoder.train.assert_called_once()
        assert result["volume"]["trained"]
        assert result["sentiment"]["trained"]
        assert result["source"]["trained"]
        assert result["topic"]["trained"]
        assert result["autoencoder"]["trained"]

    def test_train_all_passes_ticker_to_relevant_detectors(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_sentiment = MagicMock()
        mock_autoencoder = MagicMock()

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.ticker = "AAPL"
        d.volume = mock_volume
        d.sentiment = mock_sentiment
        d.source = MagicMock()
        d.topic = MagicMock()
        d.autoencoder = mock_autoencoder

        mock_db = MagicMock()
        d.train_all(mock_db)
        mock_volume.train.assert_called_with(mock_db, "AAPL")
        mock_sentiment.train.assert_called_with(mock_db, "AAPL")
        mock_autoencoder.train.assert_called_with(mock_db, "AAPL")


class TestAnomalyDetectorPredictArticle:
    def test_predict_article_no_train_all_zeros(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_sentiment = MagicMock()
        mock_source = MagicMock()
        mock_topic = MagicMock()
        mock_autoencoder = MagicMock()
        for m in (mock_volume, mock_sentiment, mock_source, mock_topic, mock_autoencoder):
            m.trained = False

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.volume = mock_volume
        d.sentiment = mock_sentiment
        d.source = mock_source
        d.topic = mock_topic
        d.autoencoder = mock_autoencoder

        result = d.predict_article(MagicMock(), MagicMock())
        assert result["anomaly_score"] == 0.0
        assert not result["is_anomaly"]
        assert result["details"] == {
            "volume": 0.0,
            "sentiment": 0.0,
            "source": 0.0,
            "topic": 0.0,
            "autoencoder": 0.0,
        }

    def test_predict_article_uses_trained_detectors_only(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_sentiment = MagicMock()
        mock_source = MagicMock()
        mock_topic = MagicMock()
        mock_autoencoder = MagicMock()

        mock_volume.trained = True
        mock_volume.predict_article.return_value = 1.0
        for m in (mock_sentiment, mock_source, mock_topic, mock_autoencoder):
            m.trained = False

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.volume = mock_volume
        d.sentiment = mock_sentiment
        d.source = mock_source
        d.topic = mock_topic
        d.autoencoder = mock_autoencoder

        result = d.predict_article(MagicMock(), MagicMock())
        mock_volume.predict_article.assert_called_once()
        for m in (mock_sentiment, mock_source, mock_topic, mock_autoencoder):
            m.predict_article.assert_not_called()
        assert result["details"]["volume"] == 1.0

    def test_predict_article_computes_weighted_score(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_sentiment = MagicMock()
        mock_source = MagicMock()
        mock_topic = MagicMock()
        mock_autoencoder = MagicMock()

        for m in (mock_volume, mock_sentiment, mock_source, mock_topic, mock_autoencoder):
            m.trained = True
        mock_volume.predict_article.return_value = 0.5
        mock_sentiment.predict_article.return_value = 0.5
        mock_source.predict_article.return_value = 0.5
        mock_topic.predict_article.return_value = 0.5
        mock_autoencoder.predict_article.return_value = 0.5

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.volume = mock_volume
        d.sentiment = mock_sentiment
        d.source = mock_source
        d.topic = mock_topic
        d.autoencoder = mock_autoencoder

        with patch("src.analysis.anomaly.detector.settings") as mock_settings:
            mock_settings.ml_anomaly_weight_volume = 0.25
            mock_settings.ml_anomaly_weight_sentiment = 0.25
            mock_settings.ml_anomaly_weight_source = 0.2
            mock_settings.ml_anomaly_weight_topic = 0.15
            mock_settings.ml_anomaly_weight_autoencoder = 0.15

            result = d.predict_article(MagicMock(), MagicMock())
            expected = (
                0.5 * 0.25
                + 0.5 * 0.25
                + 0.5 * 0.2
                + 0.5 * 0.15
                + 0.5 * 0.15
            ) / 1.0
            assert result["anomaly_score"] == pytest.approx(expected)

    def test_predict_article_above_threshold(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_volume.trained = True
        mock_volume.predict_article.return_value = 1.0

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.volume = mock_volume
        for attr in ("sentiment", "source", "topic", "autoencoder"):
            m = MagicMock()
            m.trained = True
            m.predict_article.return_value = 0.0
            setattr(d, attr, m)

        with patch("src.analysis.anomaly.detector.settings") as mock_settings:
            mock_settings.ml_anomaly_weight_volume = 0.5
            mock_settings.ml_anomaly_weight_sentiment = 0.0
            mock_settings.ml_anomaly_weight_source = 0.0
            mock_settings.ml_anomaly_weight_topic = 0.0
            mock_settings.ml_anomaly_weight_autoencoder = 0.0

            result = d.predict_article(MagicMock(), MagicMock())
            assert result["is_anomaly"]
            assert result["anomaly_score"] >= 0.5

    def test_predict_article_below_threshold(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_volume.trained = True
        mock_volume.predict_article.return_value = 0.1

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.volume = mock_volume
        for attr in ("sentiment", "source", "topic", "autoencoder"):
            m = MagicMock()
            m.trained = True
            m.predict_article.return_value = 0.0
            setattr(d, attr, m)

        with patch("src.analysis.anomaly.detector.settings") as mock_settings:
            mock_settings.ml_anomaly_weight_volume = 0.5
            mock_settings.ml_anomaly_weight_sentiment = 0.0
            mock_settings.ml_anomaly_weight_source = 0.0
            mock_settings.ml_anomaly_weight_topic = 0.0
            mock_settings.ml_anomaly_weight_autoencoder = 0.0

            result = d.predict_article(MagicMock(), MagicMock())
            assert not result["is_anomaly"]
            assert result["anomaly_score"] < 0.5

    def test_predict_article_zero_total_weight_returns_zero(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_volume.trained = True
        mock_volume.predict_article.return_value = 0.0

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.volume = mock_volume
        for attr in ("sentiment", "source", "topic", "autoencoder"):
            m = MagicMock()
            m.trained = True
            m.predict_article.return_value = 0.0
            setattr(d, attr, m)

        result = d.predict_article(MagicMock(), MagicMock())
        assert result["anomaly_score"] == 0.0
        assert not result["is_anomaly"]

    def test_predict_article_returns_rounded_score(self):
        from src.analysis.anomaly.detector import AnomalyDetector

        mock_volume = MagicMock()
        mock_volume.trained = True
        mock_volume.predict_article.return_value = 0.33333333

        d = AnomalyDetector.__new__(AnomalyDetector)
        d.volume = mock_volume
        for attr in ("sentiment", "source", "topic", "autoencoder"):
            m = MagicMock()
            m.trained = True
            m.predict_article.return_value = 0.0
            setattr(d, attr, m)

        with patch("src.analysis.anomaly.detector.settings") as mock_settings:
            mock_settings.ml_anomaly_weight_volume = 1.0
            mock_settings.ml_anomaly_weight_sentiment = 0.0
            mock_settings.ml_anomaly_weight_source = 0.0
            mock_settings.ml_anomaly_weight_topic = 0.0
            mock_settings.ml_anomaly_weight_autoencoder = 0.0

            result = d.predict_article(MagicMock(), MagicMock())
            assert result["anomaly_score"] == 0.3333
