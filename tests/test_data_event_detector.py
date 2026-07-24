from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.data.event_detector import DataSentimentDivergenceDetector, EventDetector


class TestEventDetector:
    def test_init_default_threshold(self):
        detector = EventDetector()
        assert detector.threshold == 0.80

    def test_init_custom_threshold(self):
        detector = EventDetector(similarity_threshold=0.5)
        assert detector.threshold == 0.5

    def test_detect_related_articles_empty_candidates(self):
        detector = EventDetector()
        ref = MagicMock(embedding=[0.1, 0.2, 0.3])
        assert detector.detect_related_articles(ref, []) == []

    def test_detect_related_articles_no_embedding(self):
        detector = EventDetector(0.0)
        ref = MagicMock(embedding=None)
        candidate = MagicMock(embedding=[0.1, 0.2, 0.3])
        result = detector.detect_related_articles(ref, [candidate])
        assert len(result) == 0

    def test_cosine_similarity(self):
        detector = EventDetector()
        sim = detector._cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert abs(sim - 1.0) < 0.001

    def test_cosine_similarity_orthogonal(self):
        detector = EventDetector()
        sim = detector._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim - 0.0) < 0.001

    def test_cosine_similarity_empty(self):
        detector = EventDetector()
        assert detector._cosine_similarity([], []) == 0.0

    def test_detect_related_articles_with_similar(self):
        detector = EventDetector(similarity_threshold=0.0)
        ref = MagicMock(embedding=[1.0, 0.0, 0.0])
        cand = MagicMock(embedding=[1.0, 0.0, 0.0], id=2)
        result = detector.detect_related_articles(ref, [cand])
        assert len(result) == 1


class TestDataSentimentDivergenceDetector:
    def test_init_defaults(self):
        detector = DataSentimentDivergenceDetector()
        assert detector.threshold == 0.4

    def test_init_custom_threshold(self):
        detector = DataSentimentDivergenceDetector(divergence_threshold=0.5)
        assert detector.threshold == 0.5

    def test_analyze_empty(self):
        detector = DataSentimentDivergenceDetector()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = []
        result = detector.analyze_sector_sentiment_divergence("unknown", mock_db)
        assert result["has_divergence"] is False
        assert result["consensus"] == "no_data"

    def test_analyze_with_data(self):
        detector = DataSentimentDivergenceDetector()
        mock_db = MagicMock()
        inst = MagicMock(id=1)
        mock_db.query.return_value.filter_by.return_value.all.return_value = [inst]
        mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = []
        result = detector.analyze_sector_sentiment_divergence("banking", mock_db)
        assert isinstance(result, dict)
