from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.data.geopolitical_risk_engine import (
    EWMA_ALPHA,
    GEO_RISK_WEIGHTS,
    REGION_KEYWORDS,
    DetectedEvent,
    GeopoliticalRiskEngine,
)


@pytest.fixture
def engine():
    return GeopoliticalRiskEngine()


# ── Region extraction ────────────────────────────────────────────────────────


class TestExtractRegion:
    def test_russian_keywords(self, engine):
        assert engine.extract_region_from_news("Путин подписал указ", "") == "russia"

    def test_chinese_keywords(self, engine):
        assert engine.extract_region_from_news("Китай вводит пошлины", "") == "china"

    def test_no_match(self, engine):
        assert engine.extract_region_from_news("Солнечная погода", "") is None

    def test_multiple_regions(self, engine):
        countries = engine.extract_countries("Путин и Байден встретились", "")
        assert "russia" in countries
        assert "usa" in countries


# ── Event detection ──────────────────────────────────────────────────────────


class TestEventDetection:
    def test_detect_sanctions_event(self, engine):
        article = MagicMock(title="Новые санкции против РФ", summary="", published_at=datetime.now(timezone.utc))
        events = engine.detect_events([article])
        assert len(events) == 1
        assert events[0].category == "sanctions"
        assert events[0].severity == 7.0  # matches "санкции против" pattern first

    def test_detect_conflict(self, engine):
        article = MagicMock(title="Военный конфликт в регионе", summary="", published_at=datetime.now(timezone.utc))
        events = engine.detect_events([article])
        assert len(events) == 1
        assert events[0].category == "conflict"

    def test_no_event(self, engine):
        article = MagicMock(title="Спортивные новости", summary="", published_at=datetime.now(timezone.utc))
        events = engine.detect_events([article])
        assert len(events) == 0


class TestDetectedEvent:
    def test_decay(self):
        event = DetectedEvent("sanctions", 8.0, "russia", "text", datetime.now(timezone.utc) - timedelta(days=30))
        decayed = event.decayed_severity(datetime.now(timezone.utc))
        assert decayed == pytest.approx(4.0, rel=0.1)  # half-life of 30 days


class TestEventRisk:
    def test_no_events(self, engine):
        result = engine.calculate_event_risk([])
        assert all(v == 0.0 for v in result.values())

    def test_with_events(self, engine):
        events = [
            DetectedEvent("sanctions", 8.0, "russia", "text", datetime.now(timezone.utc)),
            DetectedEvent("conflict", 7.0, "iran", "text", datetime.now(timezone.utc)),
        ]
        result = engine.calculate_event_risk(events)
        assert result["sanctions"] == 8.0
        assert result["conflict"] == 7.0


# ── Subcategory score ────────────────────────────────────────────────────────


class TestSubcategoryScore:
    def test_no_relevant_articles(self, engine):
        articles = [MagicMock(is_relevant=False, subcategory="sanctions")]
        result = engine.calculate_subcategory_score("sanctions", articles)
        assert result["risk_score"] == 0.0

    def test_with_relevant_articles(self, engine):
        article = MagicMock(
            is_relevant=True,
            subcategory="sanctions",
            published_at=datetime.now(timezone.utc),
            sentiment="negative",
            impact_score=7.0,
            source_name="rbc",
        )
        result = engine.calculate_subcategory_score("sanctions", [article])
        assert result["risk_score"] > 0
        assert result["article_count"] == 1


# ── EWMA ──────────────────────────────────────────────────────────────────────


class TestEWMA:
    def test_empty(self, engine):
        assert engine.compute_ewma([]) == 0.0

    def test_single(self, engine):
        assert engine.compute_ewma([5.0]) == 5.0

    def test_smoothing(self, engine):
        result = engine.compute_ewma([5.0, 6.0, 7.0])
        expected = EWMA_ALPHA * 7.0 + (1 - EWMA_ALPHA) * (EWMA_ALPHA * 6.0 + (1 - EWMA_ALPHA) * 5.0)
        assert result == pytest.approx(expected)


# ── Forward projection ────────────────────────────────────────────────────────


class TestForwardProjection:
    def test_insufficient_history(self, engine):
        assert engine.forward_projection([5.0], 30) == 5.0

    def test_upward_trend(self, engine):
        result = engine.forward_projection([3.0, 4.0, 5.0, 6.0, 7.0], 10)
        assert result > 7.0  # upward projection

    def test_downward_trend(self, engine):
        result = engine.forward_projection([7.0, 6.0, 5.0, 4.0, 3.0], 10)
        assert result < 3.0

    def test_capped(self, engine):
        result = engine.forward_projection([9.0, 9.5, 10.0], 30)
        assert result <= 10.0


# ── Sector geo multiplier ─────────────────────────────────────────────────────


class TestSectorGeoMultiplier:
    def test_known_sector(self, engine):
        subcat_scores = {"sanctions": 5.0, "conflict": 3.0, "trade_war": 2.0, "diplomacy": 1.0}
        impact = engine.sector_geo_multiplier("Нефть", subcat_scores)
        assert impact["sanctions"] == 7.0  # 5.0 * 1.4

    def test_unknown_sector(self, engine):
        impact = engine.sector_geo_multiplier("Unknown", {"sanctions": 5.0})
        assert impact["sanctions"] == 5.0  # default multiplier 1.0


# ── Alert level ──────────────────────────────────────────────────────────────


class TestAlertLevel:
    def test_low(self):
        assert GeopoliticalRiskEngine.get_risk_alert_level(2.0) == "low"

    def test_medium(self):
        assert GeopoliticalRiskEngine.get_risk_alert_level(4.0) == "medium"

    def test_high(self):
        assert GeopoliticalRiskEngine.get_risk_alert_level(6.0) == "high"

    def test_critical(self):
        assert GeopoliticalRiskEngine.get_risk_alert_level(8.0) == "critical"


# ── Emerging threats ──────────────────────────────────────────────────────────


class TestEmergingThreats:
    def test_no_threats(self, engine):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [
            MagicMock(risk_score=5.0),  # today
            MagicMock(risk_score=5.0),  # yesterday
            MagicMock(risk_score=5.0),  # week ago
        ]
        threats = engine.identify_emerging_threats(db)
        assert len(threats) == 0

    def test_daily_spike(self, engine):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [
            MagicMock(risk_score=8.0),  # today
            MagicMock(risk_score=5.0),  # yesterday
            MagicMock(risk_score=5.0),  # week ago
        ]
        threats = engine.identify_emerging_threats(db)
        assert any(t["type"] == "spike" for t in threats)
        spike = [t for t in threats if t["type"] == "spike"][0]
        assert spike["magnitude"] == 3.0


# ── Sector geo impact ────────────────────────────────────────────────────────


class TestSectorGeoImpact:
    def test_basic(self, engine):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = engine.sector_geo_impact("Нефть", db)
        assert result["sector"] == "Нефть"
        assert "base_geo_risk" in result
        assert "adjusted_risk" in result
        assert "subcategory_breakdown" in result


# ── Market impact assessment ──────────────────────────────────────────────────


class TestMarketImpactAssessment:
    def test_basic(self, engine):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        db.query.return_value.filter.return_value.first.side_effect = [
            None,  # today geo risk
            None,  # yesterday
            None,  # week
        ]
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = engine.market_impact_assessment(db)
        assert "overall_risk" in result
        assert "alert_level" in result
        assert "most_affected_sectors" in result


# ── Daily calculation ────────────────────────────────────────────────────────


class TestDailyGeopoliticalRisk:
    def test_no_articles(self, engine):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        result = engine.calculate_daily_geopolitical_risk(db)
        assert result["risk_score"] == 0.0
        assert result["confidence"] == 0.0

    def test_with_articles(self, engine):
        db = MagicMock()
        # geo articles
        article = MagicMock(
            is_relevant=True,
            subcategory="sanctions",
            title="Новые санкции",
            summary="против РФ",
            published_at=datetime.now(timezone.utc),
            sentiment="negative",
            impact_score=8.0,
            source_name="rbc",
            category="GEOPOLITICAL",
        )
        db.query.return_value.filter.return_value.all.return_value = [article]
        # history
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with patch.object(engine, "detect_events", return_value=[]):
            result = engine.calculate_daily_geopolitical_risk(db)

        assert result["risk_score"] > 0
        assert "ewma_score" in result
        assert "forward_7d" in result
        assert "forward_30d" in result
        assert "events" in result


# ── Store ────────────────────────────────────────────────────────────────────


class TestStoreGeopoliticalRisk:
    def test_success(self, engine):
        db = MagicMock()
        risk = {
            "date": datetime.now(timezone.utc).date(),
            "risk_score": 5.5,
            "subcategories": {
                "sanctions": {"risk_score": 6.0},
                "conflict": {"risk_score": 5.0},
                "trade_war": {"risk_score": 4.0},
                "diplomacy": {"risk_score": 3.0},
            },
            "ewma_score": 5.2,
            "news_score": 5.5,
            "event_score": 1.0,
            "forward_7d": 5.8,
            "forward_30d": 6.2,
            "confidence": 0.8,
            "total_article_count": 10,
            "unique_sources": 3,
            "source_diversity_score": 0.3,
            "event_count": 2,
        }
        result = engine.store_geopolitical_risk(risk, db)
        assert result is True
        db.add.assert_called_once()

    def test_failure(self, engine):
        db = MagicMock()
        db.add.side_effect = Exception("DB error")
        risk = {
            "date": datetime.now(timezone.utc).date(),
            "risk_score": 5.5,
            "subcategories": {
                "sanctions": {"risk_score": 6.0},
                "conflict": {"risk_score": 5.0},
                "trade_war": {"risk_score": 4.0},
                "diplomacy": {"risk_score": 3.0},
            },
            "total_article_count": 10,
            "unique_sources": 3,
        }
        result = engine.store_geopolitical_risk(risk, db)
        assert result is False


# ── Trend ────────────────────────────────────────────────────────────────────


class TestGeopoliticalTrend:
    def test_no_history(self, engine):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        result = engine.calculate_geopolitical_trend(db)
        assert result["trend"] == "no_data"

    def test_with_history(self, engine):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            MagicMock(risk_score=3.0, date="2024-01-01"),
            MagicMock(risk_score=5.0, date="2024-01-02"),
            MagicMock(risk_score=7.0, date="2024-01-03"),
        ]
        result = engine.calculate_geopolitical_trend(db, days=30)
        assert result["trend"] == "up"
        assert result["current_risk"] == 7.0
        assert result["ewma"] > 0


# ── weights ──────────────────────────────────────────────────────────────────


class TestWeights:
    def test_weights_sum_to_one(self):
        assert sum(GEO_RISK_WEIGHTS.values()) == pytest.approx(1.0)


class TestRegionKeywords:
    def test_has_expected_regions(self):
        for region in ["russia", "china", "europe", "usa", "middle_east", "asia", "africa", "latin_america"]:
            assert region in REGION_KEYWORDS
