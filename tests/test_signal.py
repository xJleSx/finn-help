"""Tests for SignalFusionEngine"""
from __future__ import annotations

import pytest


@pytest.fixture
def engine():
    from src.signal.engine import SignalFusionEngine
    return SignalFusionEngine()


class TestFuse:
    def test_returns_dict(self, engine):
        result = engine.fuse(ticker="SBER", technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": ["тест"]})
        assert isinstance(result, dict)

    def test_has_ticker(self, engine):
        result = engine.fuse(ticker="SBER", technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []})
        assert result["ticker"] == "SBER"

    def test_has_action_key(self, engine):
        result = engine.fuse(ticker="SBER", technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []})
        assert "action" in result

    def test_has_confidence_key(self, engine):
        result = engine.fuse(ticker="SBER", technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []})
        assert "confidence" in result

    def test_confidence_between_0_and_1(self, engine):
        result = engine.fuse(ticker="SBER", technical={"action": "BUY", "confidence": 0.8, "score": 0.8, "reasons": []})
        assert 0 <= result["confidence"] <= 1

    def test_buy_on_strong_positive(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.9, "score": 0.9, "reasons": ["сильный тренд"]},
            fundamental={"risk": 0.1, "anomalies": []},
            geo={"score": 1.0},
        )
        assert result["action"] == "BUY"

    def test_sell_on_strong_negative(self, engine):
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "SELL", "confidence": 0.9, "score": -0.9, "reasons": ["сильный спад"]},
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
            technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": ["RSI нейтрально"]},
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
        result = engine.fuse(ticker="SBER", technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []})
        assert "weighted_score" in result

    def test_has_max_portfolio_pct(self, engine):
        result = engine.fuse(ticker="SBER", technical={"action": "BUY", "confidence": 0.9, "score": 0.9, "reasons": []})
        assert 0 < result["max_portfolio_pct"] <= 30

    def test_has_components(self, engine):
        result = engine.fuse(ticker="SBER", technical={"action": "HOLD", "confidence": 0.5, "score": 0.0, "reasons": []})
        assert "components" in result


class TestMaxPosition:
    def test_buy_max_30(self, engine):
        assert engine._calc_max_position("BUY", 0.0, 0.0) == 30

    def test_cautious_buy_max_15(self, engine):
        assert engine._calc_max_position("CAUTIOUS_BUY", 0.0, 0.0) == 15

    def test_high_geo_reduces_limit(self, engine):
        assert engine._calc_max_position("BUY", 8.0, 0.0) == 10

    def test_high_fund_risk_reduces_limit(self, engine):
        assert engine._calc_max_position("BUY", 0.0, 0.7) == 10

    def test_sell_max_5(self, engine):
        assert engine._calc_max_position("SELL", 0.0, 0.0) == 5
