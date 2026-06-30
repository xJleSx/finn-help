from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.alerts.scorer import build_alert, classify_priority
from src.db.models import News


class TestClassifyPriority:
    def test_critical_high_anomaly(self):
        priority, reason = classify_priority(0.85, 0.0, False)
        assert priority == "CRITICAL"

    def test_critical_portfolio_high_return(self):
        priority, reason = classify_priority(0.5, 0.025, True)
        assert priority == "CRITICAL"

    def test_high_anomaly(self):
        priority, reason = classify_priority(0.65, 0.0, False)
        assert priority == "HIGH"

    def test_high_portfolio_moderate_return(self):
        priority, reason = classify_priority(0.0, 0.012, True)
        assert priority == "HIGH"

    def test_medium_anomaly(self):
        priority, reason = classify_priority(0.45, 0.0, False)
        assert priority == "MEDIUM"

    def test_medium_return(self):
        priority, reason = classify_priority(0.0, 0.005, False)
        assert priority == "MEDIUM"

    def test_low_everything_low(self):
        priority, reason = classify_priority(0.0, 0.0, False)
        assert priority == "LOW"

    def test_reason_anomaly_detected(self):
        priority, reason = classify_priority(0.55, 0.0, False)
        assert "anomaly detected" in reason

    def test_reason_predicted_return(self):
        priority, reason = classify_priority(0.0, 0.01, False)
        assert "predicted" in reason

    def test_reason_in_portfolio(self):
        priority, reason = classify_priority(0.0, 0.0, True)
        assert "in your portfolio" in reason


class TestBuildAlert:
    def test_full_alert_structure(self):
        article = News(
            id=1, title="Test article", category="COMPANY",
            subcategory="earnings", source_name="Interfax",
            published_at=datetime.now(timezone.utc),
        )
        anomaly = {"anomaly_score": 0.5, "is_anomaly": True, "details": {}}
        impact = {"predicted_return": 0.01, "confidence": 0.8, "model_loaded": True}
        alert = build_alert(article, "SBER", anomaly, impact, in_portfolio=True)
        assert alert["news_id"] == 1
        assert alert["ticker"] == "SBER"
        assert alert["category"] == "COMPANY"
        assert alert["priority"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        assert 0.0 <= alert["priority_score"] <= 1.0
        assert alert["in_portfolio"] is True

    def test_alert_not_in_portfolio(self):
        article = News(id=2, title="Test", published_at=datetime.now(timezone.utc))
        anomaly = {"anomaly_score": 0.0, "is_anomaly": False, "details": {}}
        impact = {"predicted_return": 0.0, "confidence": 0.0, "model_loaded": False}
        alert = build_alert(article, "GAZP", anomaly, impact, in_portfolio=False)
        assert alert["in_portfolio"] is False
        assert alert["priority"] == "LOW"

    def test_alert_without_published_at(self):
        article = News(id=3, title="No date")
        anomaly = {"anomaly_score": 0.0, "is_anomaly": False, "details": {}}
        impact = {"predicted_return": 0.0, "confidence": 0.0, "model_loaded": False}
        alert = build_alert(article, "SBER", anomaly, impact, in_portfolio=False)
        assert alert["published_at"] is not None
