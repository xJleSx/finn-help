from __future__ import annotations

import pytest

from src.geo.sentiment_divergence import SentimentDivergenceDetector


class TestVariance:
    def setup_method(self):
        self.detector = SentimentDivergenceDetector()

    def test_empty(self):
        assert self.detector._variance([]) == 0.0

    def test_constant(self):
        assert self.detector._variance([1.0, 1.0, 1.0]) == 0.0

    def test_variable(self):
        v = self.detector._variance([0.0, 1.0])
        assert v == 0.25

    def test_single_value(self):
        assert self.detector._variance([5.0]) == 0.0


class TestDetect:
    def setup_method(self):
        self.detector = SentimentDivergenceDetector()

    def test_no_data(self):
        result = self.detector.detect(db=None, news_list=None)
        assert result["divergence"] == 0.0
        assert "нет данных" in str(result["signals"])

    def test_news_list_positive(self):
        news_list = [
            {"sentiment_score": 0.1},
            {"sentiment_score": 0.2},
            {"sentiment_score": 0.3},
        ]
        result = self.detector.detect(news_list=news_list)
        assert result["sources_count"] == 3
        assert result["mean_sentiment"] > 0

    def test_high_divergence_signal(self):
        scores = [0.9, -0.8, 0.85, -0.7]
        news_list = [{"sentiment_score": s} for s in scores]
        result = self.detector.detect(news_list=news_list)
        assert result["divergence"] > 0.6
        assert "расхождение" in str(result["signals"])

    def test_moderate_divergence(self):
        scores = [0.5, 0.0, -0.3]
        news_list = [{"sentiment_score": s} for s in scores]
        result = self.detector.detect(news_list=news_list)
        assert result["divergence"] <= 0.6

    def test_empty_scores_list(self):
        result = self.detector.detect(news_list=[])
        assert result["sources_count"] == 0

    def test_negative_mean_with_divergence(self):
        scores = [0.5, 0.4, 0.6]
        news_list = [{"sentiment_score": s} for s in scores]
        result = self.detector.detect(news_list=news_list)
        assert result["mean_sentiment"] > 0.3
