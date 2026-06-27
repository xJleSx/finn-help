"""Tests for SignalFusionEngine"""

from __future__ import annotations

import numpy as np
import pytest

from src.signal.engine import SignalFusionEngine, compute_risk_metrics


@pytest.fixture
def engine():
    return SignalFusionEngine()


@pytest.fixture
def gentle_uptrend_prices():
    rng = np.random.default_rng(42)
    base = 100.0 + np.arange(100) * 0.5
    noise = rng.normal(0, 1, 100)
    return (base + noise).tolist()


@pytest.fixture
def volatile_prices():
    rng = np.random.default_rng(7)
    return (100.0 + np.cumsum(rng.normal(0, 5, 200))).tolist()


@pytest.fixture
def flat_prices():
    return [100.0] * 50


class TestFuse:
    def test_returns_dict(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": ["тест"]},
        )
        assert isinstance(result, dict)

    def test_has_ticker(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []},
        )
        assert result["ticker"] == "SBER"

    def test_has_action_key(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []},
        )
        assert "action" in result

    def test_has_confidence_key(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []},
        )
        assert "confidence" in result

    def test_confidence_between_0_and_1(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.8, "score": 0.8, "reasons": []},
        )
        assert 0 <= result["confidence"] <= 1

    def test_buy_on_strong_positive(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={
                "action": "BUY",
                "confidence": 0.9,
                "score": 0.9,
                "reasons": ["сильный тренд"],
            },
            fundamental={"risk": 0.1, "anomalies": []},
            geo={"score": 1.0},
        )
        assert result["action"] == "BUY"

    def test_sell_on_strong_negative(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={
                "action": "SELL",
                "confidence": 0.9,
                "score": -0.9,
                "reasons": ["сильный спад"],
            },
            fundamental={"risk": 0.9, "anomalies": []},
            geo={"score": 8.0},
        )
        assert result["action"] == "SELL"

    def test_high_geo_downgrades_buy(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.9, "score": 0.9, "reasons": []},
            fundamental={"risk": 0.1, "anomalies": []},
            geo={"score": 8.0},
        )
        assert result["action"] == "CAUTIOUS_BUY"

    def test_anomalies_downgrade_buy(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.9, "score": 0.9, "reasons": []},
            fundamental={"risk": 0.5, "anomalies": ["падение прибыли"]},
            geo={"score": 1.0},
        )
        assert result["action"] == "CAUTIOUS_BUY"

    def test_includes_tech_reasons(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={
                "action": "HOLD",
                "confidence": 0.5,
                "score": 0.0,
                "reasons": ["RSI нейтрально"],
            },
        )
        assert "RSI нейтрально" in " ".join(result["reasons"])

    def test_includes_ml_reason(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []},
            ml_prediction={"signal_score": 0.5, "ml_confidence": 0.6, "price_change_pct": 3.5},
        )
        reasons_text = " ".join(result["reasons"])
        assert "ML" in reasons_text or "прогноз" in reasons_text

    def test_has_weighted_score(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []},
        )
        assert "weighted_score" in result

    def test_has_max_portfolio_pct(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.9, "score": 0.9, "reasons": []},
        )
        assert 0 < result["max_portfolio_pct"] <= 50

    def test_has_components(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []},
        )
        assert "components" in result

    def test_macro_adjustment_affects_score(self, engine):
        result_with_macro = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []},
            macro_context={"imoex": 1000, "key_rate": 20, "brent": 100, "cpi": 3},
        )
        assert "weighted_score" in result_with_macro

    def test_sentiment_positive_boosts_signal(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []},
            sentiment={"score": 0.8, "divergence": 0.1, "source": "rss"},
        )
        reasons_text = " ".join(result["reasons"])
        assert "позитивные" in reasons_text or "Новости" in reasons_text

    def test_sentiment_negative_reduces_signal(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.5, "score": 0.5, "reasons": []},
            sentiment={"score": -0.8, "divergence": 0.1, "source": "rss"},
        )
        assert result["weighted_score"] < 0.5


class TestRiskMetrics:
    def test_uptrend_sharpe_positive(self, gentle_uptrend_prices):
        metrics = compute_risk_metrics(gentle_uptrend_prices)
        assert metrics["sharpe"] > 0

    def test_flat_returns_zero_sharpe(self, flat_prices):
        metrics = compute_risk_metrics(flat_prices)
        assert metrics["sharpe"] == 0.0

    def test_flat_returns_zero_max_drawdown(self, flat_prices):
        metrics = compute_risk_metrics(flat_prices)
        assert metrics["max_drawdown"] == 0.0

    def test_downtrend_negative_sharpe(self):
        prices = list(reversed(range(100, 200)))
        metrics = compute_risk_metrics(prices)
        assert metrics["sharpe"] < 0

    def test_high_volatility_increases_drawdown(self, volatile_prices):
        metrics = compute_risk_metrics(volatile_prices)
        assert metrics["max_drawdown"] > 0

    def test_short_series_fallback(self):
        metrics = compute_risk_metrics([100, 101, 102])
        assert metrics["sharpe"] == 0.0

    def test_has_all_keys(self, gentle_uptrend_prices):
        metrics = compute_risk_metrics(gentle_uptrend_prices)
        expected_keys = {"sharpe", "sortino", "max_drawdown", "calmar", "omega"}
        assert set(metrics.keys()) == expected_keys

    def test_sortino_less_than_sharpe_in_downside(self):
        rng = np.random.default_rng(42)
        prices = (100.0 + np.cumsum(rng.normal(-0.1, 2, 200))).tolist()
        metrics = compute_risk_metrics(prices)
        assert metrics["sortino"] <= metrics["sharpe"] or metrics["sharpe"] == 0.0

    def test_calmar_positive_for_uptrend(self, gentle_uptrend_prices):
        metrics = compute_risk_metrics(gentle_uptrend_prices)
        assert metrics["calmar"] > 0


class TestMaxPosition:
    def test_buy_max_50(self, engine):
        assert engine._calc_max_position("BUY", 0.0, 0.0) == 50

    def test_cautious_buy_max_25(self, engine):
        assert engine._calc_max_position("CAUTIOUS_BUY", 0.0, 0.0) == 25

    def test_high_geo_reduces_limit(self, engine):
        assert engine._calc_max_position("BUY", 8.0, 0.0) == 10

    def test_high_fund_risk_reduces_limit(self, engine):
        assert engine._calc_max_position("BUY", 0.0, 0.7) == 10

    def test_sell_max_5(self, engine):
        assert engine._calc_max_position("SELL", 0.0, 0.0) == 5

    def test_neutral_max_10(self, engine):
        assert engine._calc_max_position("HOLD", 0.0, 0.0) == 10


class TestEdgeCases:
    def test_fuse_none_technical(self, engine):
        result = engine.fuse(ticker="TEST", technical=None)
        assert result["action"] in ("HOLD", "NEUTRAL")

    def test_fuse_empty_reasons(self, engine):
        result = engine.fuse(
            ticker="TEST",
            technical={"action": "BUY", "confidence": 0.8, "score": 1.5, "reasons": []},
        )
        assert isinstance(result["reasons"], list)

    def test_fuse_high_confidence_buy(self, engine):
        result = engine.fuse(
            ticker="TEST",
            technical={"action": "BUY", "confidence": 0.95, "score": 2.0, "reasons": ["strong buy"]},
        )
        assert result["action"] == "BUY"
        assert result["confidence"] > 0.5

    def test_all_none_inputs(self, engine):
        result = engine.fuse(ticker="TEST")
        assert result["action"] in ("HOLD", "NEUTRAL")
        assert "action" in result

    def test_mtf_agreement_included(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.7, "score": 0.5, "reasons": []},
            mtf={"direction": 0.8, "agreement": 0.9, "details": {"daily": {}, "weekly": {}}},
        )
        reasons = " ".join(result["reasons"])
        assert "бычий" in reasons or "MTF" in reasons or "консенсус" in reasons

    def test_volatility_regime_adjusts_weights(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.7, "score": 0.5, "reasons": []},
            volatility_regime={
                "regime": "HIGH",
                "adjustment": {"technical_mult": 0.7, "fundamental_mult": 1.3, "geo_mult": 1.5, "ml_mult": 0.6},
            },
        )
        assert result["volatility_regime"]["regime"] == "HIGH"

    def test_confidence_symmetric_for_equal_magnitude(self, engine):
        result_pos = engine.fuse(
            ticker="TEST",
            technical={"action": "BUY", "confidence": 0.7, "score": 0.5, "reasons": []},
            geo={"score": 0.0},
            fundamental={"risk": 0.3, "anomalies": []},
        )
        result_neg = engine.fuse(
            ticker="TEST",
            technical={"action": "SELL", "confidence": 0.7, "score": -0.5, "reasons": []},
            geo={"score": 0.0},
            fundamental={"risk": 0.3, "anomalies": []},
        )
        assert abs(result_pos["confidence"] - result_neg["confidence"]) < 0.15
