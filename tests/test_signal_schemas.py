from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.signals.schemas import (
    BatchFuseRequest,
    FusedSignal,
    MLComponent,
    RiskMetrics,
    SignalComponents,
    SignalRecord,
    TechnicalComponent,
    VolatilityRegime,
)


class TestTechnicalComponent:
    def test_defaults(self):
        c = TechnicalComponent()
        assert c.action == "NEUTRAL"
        assert c.confidence == 0.0
        assert c.score == 0.0

    def test_custom_values(self):
        c = TechnicalComponent(action="BUY", confidence=0.8, score=0.7)
        assert c.action == "BUY"


class TestMLComponent:
    def test_defaults(self):
        c = MLComponent()
        assert c.signal_score == 0.0
        assert c.target_price is None

    def test_with_target(self):
        c = MLComponent(signal_score=0.5, target_price=250.0)
        assert c.target_price == 250.0


class TestRiskMetrics:
    def test_defaults(self):
        m = RiskMetrics()
        assert m.sharpe == 0.0
        assert m.max_drawdown == 0.0

    def test_custom(self):
        m = RiskMetrics(sharpe=1.5, sortino=1.2, max_drawdown=0.15, calmar=0.8, omega=1.1)
        assert m.sharpe == 1.5


class TestVolatilityRegime:
    def test_defaults(self):
        v = VolatilityRegime()
        assert v.regime == "NORMAL"
        assert v.atr_ratio is None

    def test_high_volatility(self):
        v = VolatilityRegime(regime="HIGH", atr_ratio=2.5, hv=0.35)
        assert v.regime == "HIGH"
        assert v.atr_ratio == 2.5


class TestSignalComponents:
    def test_defaults(self):
        c = SignalComponents()
        assert c.technical.action == "NEUTRAL"
        assert c.fundamental_risk == 0.5
        assert c.geo_risk == 0.0

    def test_nested_serialization(self):
        data = {
            "technical": {"action": "BUY", "confidence": 0.9, "score": 0.8},
            "fundamental_risk": 0.2,
            "geo_risk": 3.0,
            "ml": {"signal_score": 0.6, "confidence": 0.7, "target_price": 300.0},
            "sentiment": {"score": 0.4, "source": "rss"},
            "mtf": {"direction": 0.5, "agreement": 0.8},
        }
        c = SignalComponents(**data)
        assert c.technical.action == "BUY"
        assert c.ml.target_price == 300.0

    def test_serialization_to_dict(self):
        c = SignalComponents()
        d = c.model_dump()
        assert "technical" in d
        assert d["technical"]["action"] == "NEUTRAL"


class TestFusedSignal:
    def test_minimal(self):
        s = FusedSignal(ticker="SBER")
        assert s.ticker == "SBER"
        assert s.action == "HOLD"
        assert s.confidence == 0.0

    def test_with_all_fields(self):
        s = FusedSignal(
            ticker="GAZP",
            instrument_type="stock",
            action="BUY",
            confidence=0.85,
            weighted_score=0.65,
            reasons=["сильный тренд", "низкий риск"],
            max_portfolio_pct=25,
            components=SignalComponents(
                technical=TechnicalComponent(action="BUY", confidence=0.9, score=0.8),
                fundamental_risk=0.2,
            ),
            risk_metrics=RiskMetrics(sharpe=1.5, sortino=1.2, max_drawdown=0.1, calmar=0.8, omega=1.1),
            volatility_regime=VolatilityRegime(regime="NORMAL"),
            trade_plan={"entry": 200, "stop": 180},
        )
        assert s.ticker == "GAZP"
        assert s.risk_metrics is not None
        assert s.risk_metrics.sharpe == 1.5

    def test_model_dump_includes_none(self):
        s = FusedSignal(ticker="TEST")
        d = s.model_dump()
        assert d["risk_metrics"] is None
        assert d["volatility_regime"] is None

    def test_model_dump_exclude_none(self):
        s = FusedSignal(ticker="TEST")
        d = s.model_dump(exclude_none=True)
        assert "risk_metrics" not in d

    def test_ticker_required(self):
        with pytest.raises(ValidationError):
            FusedSignal()

    def test_confidence_bounds(self):
        s = FusedSignal(ticker="T", confidence=0.5)
        assert 0 <= s.confidence <= 1


class TestSignalRecord:
    def test_minimal(self):
        r = SignalRecord(instrument_id=1, date="2026-07-17", action="BUY", confidence=0.8, fused_json={})
        assert r.instrument_id == 1
        assert r.action == "BUY"


class TestBatchFuseRequest:
    def test_defaults(self):
        r = BatchFuseRequest(tickers=["SBER", "GAZP"])
        assert len(r.tickers) == 2
        assert r.instrument_type == "stock"
        assert r.with_ml is True

    def test_with_user(self):
        r = BatchFuseRequest(tickers=["SBER"], user_id="user_1", with_ml=False)
        assert r.user_id == "user_1"
        assert r.with_ml is False
