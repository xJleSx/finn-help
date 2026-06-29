from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.data.company_risk_aggregator import (
    BASE_WEIGHTS,
    CONTAGION_COEFFICIENT,
    CompanyRiskAggregator,
)


@pytest.fixture
def aggregator():
    return CompanyRiskAggregator()


@pytest.fixture
def mock_instrument():
    inst = MagicMock()
    inst.id = 1
    inst.ticker = "SBER"
    inst.sector = "Финансы"
    return inst


# ── Sector baseline ──────────────────────────────────────────────────────────


class TestSectorBaseline:
    def test_known_sector(self):
        assert CompanyRiskAggregator._get_sector_baseline("Финансы") == 5.5

    def test_unknown_sector(self):
        assert CompanyRiskAggregator._get_sector_baseline(None) == 5.0
        assert CompanyRiskAggregator._get_sector_baseline("Новый") == 5.0


# ── Cap class ────────────────────────────────────────────────────────────────


class TestCapClass:
    def test_large(self):
        assert CompanyRiskAggregator._cap_class(1_000_000_000_000) == "large"

    def test_mid(self):
        assert CompanyRiskAggregator._cap_class(100_000_000_000) == "mid"

    def test_small(self):
        assert CompanyRiskAggregator._cap_class(10_000_000_000) == "small"

    def test_none(self):
        assert CompanyRiskAggregator._cap_class(None) == "unknown"


class TestCapMultiplier:
    def test_large_mult(self):
        assert CompanyRiskAggregator._cap_multiplier("large") == 0.85

    def test_small_mult(self):
        assert CompanyRiskAggregator._cap_multiplier("small") == 1.25

    def test_unknown_mult(self):
        assert CompanyRiskAggregator._cap_multiplier("unknown") == 1.0


# ── Volatility ───────────────────────────────────────────────────────────────


class TestComputeVolatility:
    def test_insufficient_prices(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        result = CompanyRiskAggregator._compute_volatility(db, 1)
        assert result == 5.0  # neutral default

    def test_few_prices(self):
        db = MagicMock()
        prices = [MagicMock(close=100.0), MagicMock(close=101.0)]
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = prices
        result = CompanyRiskAggregator._compute_volatility(db, 1)
        assert result == 5.0  # not enough for std

    def test_normal_volatility(self):
        db = MagicMock()
        closes = [100.0 + i for i in range(15)]
        prices = [MagicMock(close=c) for c in closes]
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = prices
        result = CompanyRiskAggregator._compute_volatility(db, 1)
        assert 0 < result <= 10


# ── Market regime ────────────────────────────────────────────────────────────


class TestMarketRegime:
    def test_normal(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(risk_score=3.0)
        db.query.return_value.filter.return_value.all.return_value = [MagicMock(risk_score=2.0)]
        result = CompanyRiskAggregator._get_market_regime(db)
        assert result == "normal"

    def test_elevated(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(risk_score=6.0)
        db.query.return_value.filter.return_value.all.return_value = [MagicMock(risk_score=5.0)]
        result = CompanyRiskAggregator._get_market_regime(db)
        assert result == "elevated"

    def test_stress(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(risk_score=8.0)
        db.query.return_value.filter.return_value.all.return_value = [MagicMock(risk_score=7.0)]
        result = CompanyRiskAggregator._get_market_regime(db)
        assert result == "stress"


# ── Weight adjustment ────────────────────────────────────────────────────────


class TestAdjustWeights:
    def test_normal(self, aggregator):
        w = aggregator._adjust_weights("normal")
        assert w["geopolitical_risk"] == BASE_WEIGHTS["geopolitical_risk"]

    def test_stress(self, aggregator):
        w = aggregator._adjust_weights("stress")
        assert w["geopolitical_risk"] == 0.40  # geo gets heavy
        assert w["company_specific_risk"] == 0.15  # compressed


# ── Contagion ────────────────────────────────────────────────────────────────


class TestContagionBoost:
    def test_no_peers(self, aggregator):
        db = MagicMock()
        db.query.return_value.join.return_value.filter.return_value.all.return_value = []
        result = CompanyRiskAggregator._contagion_boost(db, 1, "Финансы", datetime.now(timezone.utc))
        assert result == 0.0

    def test_no_sector(self, aggregator):
        db = MagicMock()
        result = CompanyRiskAggregator._contagion_boost(db, 1, None, datetime.now(timezone.utc))
        assert result == 0.0

    def test_with_high_risk_peers(self, aggregator):
        db = MagicMock()
        peer1 = MagicMock(risk_score=8.0)
        peer2 = MagicMock(risk_score=7.0)
        db.query.return_value.join.return_value.filter.return_value.all.return_value = [peer1, peer2]
        expected = ((8.0 + 7.0) / 2 - 6.0) * CONTAGION_COEFFICIENT
        result = CompanyRiskAggregator._contagion_boost(db, 1, "Финансы", datetime.now(timezone.utc))
        assert result == pytest.approx(expected)


# ── Confidence ───────────────────────────────────────────────────────────────


class TestConfidence:
    def test_full_data(self):
        c = CompanyRiskAggregator._confidence(True, True, True, True, True)
        assert c == pytest.approx(1.0)

    def test_no_data(self):
        c = CompanyRiskAggregator._confidence(False, False, False, False, False)
        assert c == 0.0


# ── Component calculators ────────────────────────────────────────────────────


class TestSectorRiskComponent:
    def test_no_sector(self, aggregator):
        inst = MagicMock(sector=None)
        result = aggregator.calculate_sector_risk_component(inst, MagicMock())
        assert result == 5.0

    def test_with_sector_history(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(risk_score=7.5)
        inst = MagicMock(sector="Финансы")
        result = aggregator.calculate_sector_risk_component(inst, db)
        assert result == 7.5

    def test_fallback_to_baseline(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        inst = MagicMock(sector="Финансы")
        result = aggregator.calculate_sector_risk_component(inst, db)
        assert result == 5.5  # baseline for Финансы


class TestGeoRiskComponent:
    def test_with_history(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(risk_score=8.0)
        result = aggregator.calculate_geopolitical_risk_component(db)
        assert result == 8.0

    def test_no_history(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = aggregator.calculate_geopolitical_risk_component(db)
        assert result == 5.0


class TestMacroRiskComponent:
    def test_no_impacts(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        result = aggregator.calculate_macro_risk_component(db)
        assert result == 5.0

    def test_with_impacts(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            MagicMock(impact_score=6.0),
            MagicMock(impact_score=8.0),
        ]
        result = aggregator.calculate_macro_risk_component(db)
        assert result == 7.0


class TestCompanySpecificRisk:
    def test_no_impacts(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        result = aggregator.calculate_company_specific_risk_component(MagicMock(id=1), db)
        assert result == 0.0

    def test_with_impacts(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            MagicMock(impact_score=3.0),
        ]
        inst = MagicMock(id=1)
        result = aggregator.calculate_company_specific_risk_component(inst, db)
        assert result == 3.0


# ── Sentiment / recency ──────────────────────────────────────────────────────


class TestSentimentMultiplier:
    def test_no_news(self, aggregator):
        db = MagicMock()
        db.query.return_value.join.return_value.filter.return_value.all.return_value = []
        result = aggregator._sentiment_multiplier(db, 1, datetime.now(timezone.utc))
        assert result == 1.0

    def test_all_positive(self, aggregator):
        db = MagicMock()
        db.query.return_value.join.return_value.filter.return_value.all.return_value = [
            MagicMock(sentiment="positive"),
            MagicMock(sentiment="positive"),
        ]
        result = aggregator._sentiment_multiplier(db, 1, datetime.now(timezone.utc))
        assert result == 0.8

    def test_all_negative(self, aggregator):
        db = MagicMock()
        db.query.return_value.join.return_value.filter.return_value.all.return_value = [
            MagicMock(sentiment="negative"),
            MagicMock(sentiment="negative"),
        ]
        result = aggregator._sentiment_multiplier(db, 1, datetime.now(timezone.utc))
        assert result == pytest.approx(1.2)


class TestRecencyBoost:
    def test_no_recency(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 0
        result = aggregator._recency_boost(db, 1, datetime.now(timezone.utc))
        assert result == 1.0

    def test_with_recency(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 5
        result = aggregator._recency_boost(db, 1, datetime.now(timezone.utc))
        assert result == pytest.approx(1.1)


# ── Main calculation (patched helpers) ────────────────────────────────────────


class TestCalculateCompanyRisk:
    def test_basic(self, aggregator, mock_instrument):
        db = MagicMock()
        # mock FundamentalMetric query — filter().order_by().first()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            MagicMock(market_cap=1e12)
        )

        with (
            patch.object(aggregator, "_get_market_regime", return_value="normal"),
            patch.object(aggregator, "_compute_volatility", return_value=3.0),
            patch.object(aggregator, "_contagion_boost", return_value=0.0),
            patch.object(aggregator, "_sentiment_multiplier", return_value=1.0),
            patch.object(aggregator, "_recency_boost", return_value=1.0),
            patch.object(
                aggregator, "calculate_sector_risk_component", return_value=4.0
            ),
            patch.object(
                aggregator, "calculate_geopolitical_risk_component", return_value=3.0
            ),
            patch.object(
                aggregator, "calculate_macro_risk_component", return_value=5.0
            ),
            patch.object(
                aggregator,
                "calculate_company_specific_risk_component",
                return_value=2.0,
            ),
        ):
            result = aggregator.calculate_company_risk(mock_instrument, db)

        assert result["instrument_id"] == 1
        assert result["ticker"] == "SBER"
        assert 0 <= result["risk_score"] <= 10
        assert result["regime"] == "normal"
        assert result["decomposition"]["sector_risk"] == 4.0
        assert result["decomposition"]["volatility_contribution"] == 0.3
        assert result["adjustments"]["cap_class"] == "large"
        assert "confidence" in result

    def test_high_risk_scenario(self, aggregator, mock_instrument):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            MagicMock(market_cap=1e9)
        )

        with (
            patch.object(aggregator, "_get_market_regime", return_value="stress"),
            patch.object(aggregator, "_compute_volatility", return_value=8.0),
            patch.object(aggregator, "_contagion_boost", return_value=0.3),
            patch.object(aggregator, "_sentiment_multiplier", return_value=1.2),
            patch.object(aggregator, "_recency_boost", return_value=1.15),
            patch.object(
                aggregator, "calculate_sector_risk_component", return_value=8.0
            ),
            patch.object(
                aggregator, "calculate_geopolitical_risk_component", return_value=9.0
            ),
            patch.object(
                aggregator, "calculate_macro_risk_component", return_value=7.0
            ),
            patch.object(
                aggregator,
                "calculate_company_specific_risk_component",
                return_value=6.0,
            ),
        ):
            result = aggregator.calculate_company_risk(mock_instrument, db)

        # Small cap unknown -> multiplier 1.0 (no FM data)
        assert result["risk_score"] >= 5.0
        assert result["regime"] == "stress"
        assert result["adjustments"]["cap_class"] == "small"
        assert result["adjustments"]["cap_multiplier"] == 1.25


# ── Batch ────────────────────────────────────────────────────────────────────


class TestBatchCalculate:
    def test_multiple_instruments(self, aggregator):
        inst1 = MagicMock(id=1, ticker="SBER", sector="Финансы")
        inst2 = MagicMock(id=2, ticker="GAZP", sector="Нефть")
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            MagicMock(market_cap=1e12)
        )

        with (
            patch.object(aggregator, "_get_market_regime", return_value="normal"),
            patch.object(aggregator, "_compute_volatility", return_value=3.0),
            patch.object(aggregator, "_contagion_boost", return_value=0.0),
            patch.object(aggregator, "_sentiment_multiplier", return_value=1.0),
            patch.object(aggregator, "_recency_boost", return_value=1.0),
            patch.object(
                aggregator, "calculate_sector_risk_component", return_value=5.0
            ),
            patch.object(
                aggregator, "calculate_geopolitical_risk_component", return_value=5.0
            ),
            patch.object(
                aggregator, "calculate_macro_risk_component", return_value=5.0
            ),
            patch.object(
                aggregator,
                "calculate_company_specific_risk_component",
                return_value=5.0,
            ),
        ):
            results = aggregator.batch_calculate_company_risks([inst1, inst2], db)

        assert 1 in results
        assert 2 in results
        assert results[1]["ticker"] == "SBER"
        assert results[2]["ticker"] == "GAZP"


# ── Store ────────────────────────────────────────────────────────────────────


class TestStoreCompanyRisk:
    def test_successful_store(self, aggregator):
        db = MagicMock()
        risk_data = {
            "instrument_id": 1,
            "ticker": "SBER",
            "date": datetime.now(timezone.utc).date(),
            "risk_score": 5.5,
            "decomposition": {"sector_risk": 4.0, "geopolitical_risk": 3.0, "macro_risk": 5.0, "company_specific_risk": 2.0, "volatility_contribution": 1.0, "contagion_contribution": 0.0},
            "recent_news_count": 10,
        }
        result = aggregator.store_company_risk(risk_data, db)
        assert result is True
        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_store_failure(self, aggregator):
        db = MagicMock()
        db.add.side_effect = Exception("DB error")
        risk_data = {
            "instrument_id": 1,
            "ticker": "SBER",
            "date": datetime.now(timezone.utc).date(),
            "risk_score": 5.5,
            "decomposition": {"sector_risk": 4.0, "geopolitical_risk": 3.0, "macro_risk": 5.0, "company_specific_risk": 2.0, "volatility_contribution": 1.0, "contagion_contribution": 0.0},
            "recent_news_count": 10,
        }
        result = aggregator.store_company_risk(risk_data, db)
        assert result is False


# ── High risk ────────────────────────────────────────────────────────────────


class TestGetHighRiskCompanies:
    def test_empty(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        results = aggregator.get_high_risk_companies(db)
        assert results == []

    def test_with_results(self, aggregator):
        db = MagicMock()
        risk_records = [MagicMock(instrument_id=1, risk_score=7.5, sector_risk=8.0, geopolitical_risk=7.0, macro_risk=6.0, company_specific_risk=5.0)]
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = risk_records
        db.query.return_value.get.return_value = MagicMock(ticker="SBER")
        results = aggregator.get_high_risk_companies(db)
        assert len(results) == 1
        assert results[0]["ticker"] == "SBER"
        assert results[0]["risk_score"] == 7.5


# ── Trend ────────────────────────────────────────────────────────────────────


class TestCompanyRiskTrend:
    def test_no_history(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        result = aggregator.get_company_risk_trend(MagicMock(ticker="SBER"), db)
        assert result["trend"] == "no_data"

    def test_with_history(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            MagicMock(risk_score=3.0, date="2024-01-01"),
            MagicMock(risk_score=5.0, date="2024-01-02"),
        ]
        result = aggregator.get_company_risk_trend(MagicMock(ticker="SBER", id=1), db)
        assert result["trend"] == "up"
        assert result["current_risk"] == 5.0


# ── Portfolio risk ───────────────────────────────────────────────────────────


class TestPortfolioRisk:
    def test_empty(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        result = aggregator.get_portfolio_risk([1, 2], db)
        assert result["portfolio_risk"] == 0.0
        assert result["instruments"] == 0

    def test_with_risks(self, aggregator):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            MagicMock(risk_score=4.0),
            MagicMock(risk_score=8.0),
            MagicMock(risk_score=6.0),
        ]
        result = aggregator.get_portfolio_risk([1, 2, 3], db)
        assert result["portfolio_risk"] == 6.0
        assert result["instruments"] == 3
        assert result["max_risk"] == 8.0
        assert result["high_risk_count"] == 1
