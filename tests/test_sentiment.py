from __future__ import annotations

import pytest


class TestAnalyzeSentiment:
    @pytest.fixture
    def analyzer(self):
        from src.collectors.sentiment import analyze_sentiment

        return analyze_sentiment

    def test_positive_text(self, analyzer):
        result = analyzer("Компания показала отличные результаты, прибыль выросла вдвое")
        assert "score" in result
        assert "keyword_score" in result
        assert "source_weight" in result
        assert result["score"] > 0

    def test_negative_text(self, analyzer):
        result = analyzer("Кризис, падение, убытки, санкции, дефолт")
        assert result["score"] < 0

    def test_neutral_text(self, analyzer):
        result = analyzer("Сегодня вторник, на улице солнечно")
        assert "score" in result

    def test_empty_text(self, analyzer):
        result = analyzer("")
        assert "score" in result

    def test_source_weight_known(self, analyzer):
        result = analyzer("текст", source_name="РБК")
        assert result["source_weight"] == 0.9

    def test_source_weight_unknown(self, analyzer):
        result = analyzer("текст", source_name="unknown_source_xyz")
        assert result["source_weight"] == 0.5


class TestSentimentDivergence:
    @pytest.fixture
    def detector(self):
        from src.geo.sentiment_divergence import SentimentDivergenceDetector

        return SentimentDivergenceDetector()

    def test_detect_with_news_list(self, detector):
        news_list = [
            {"sentiment_score": 0.5, "source_type": "rss"},
            {"sentiment_score": -0.3, "source_type": "rss"},
            {"sentiment_score": 0.1, "source_type": "rss"},
        ]
        result = detector.detect(news_list=news_list)
        assert "divergence" in result
        assert "mean_sentiment" in result
        assert "sources_count" in result
        assert result["sources_count"] == 3

    def test_detect_empty(self, detector):
        result = detector.detect(news_list=[])
        assert result["divergence"] == 0.0
        assert result["sources_count"] == 0

    def test_detect_single_source(self, detector):
        news_list = [{"sentiment_score": 0.8, "source_type": "rss"}]
        result = detector.detect(news_list=news_list)
        assert result["divergence"] == 0.0
        assert result["mean_sentiment"] == pytest.approx(0.8)
