from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.analysis.portfolio.black_litterman import (
    BlackLittermanAllocator,
    MarketView,
    MeanVarianceOptimizer,
    ViewDirection,
)
from src.analysis.rebalancing import RebalancingEngine
from src.db.models import Instrument, Portfolio, Price


@pytest.fixture
def sample_views() -> list[MarketView]:
    return [
        MarketView(ticker="A", direction="bullish", confidence=0.8, magnitude=5.0),
        MarketView(ticker="B", direction="bearish", confidence=0.6, magnitude=-3.0),
    ]


@pytest.fixture
def market_data() -> tuple[dict[str, float], pd.DataFrame]:
    tickers = ["A", "B", "C"]
    weights = {"A": 0.4, "B": 0.4, "C": 0.2}
    cov = pd.DataFrame(
        [[0.04, 0.01, 0.01], [0.01, 0.09, 0.02], [0.01, 0.02, 0.06]],
        index=tickers,
        columns=tickers,
    )
    return weights, cov


class TestBlackLittermanFormula:
    def test_implied_returns_shape(self, market_data):
        weights, cov = market_data
        alloc = BlackLittermanAllocator(weights, cov, tau=0.05)
        Pi = alloc.implied_returns()
        assert isinstance(Pi, pd.Series)
        assert list(Pi.index) == ["A", "B", "C"]

    def test_bl_adjusts_returns_with_views(self, market_data, sample_views):
        weights, cov = market_data
        alloc = BlackLittermanAllocator(weights, cov, tau=0.05)
        result = alloc.allocate(sample_views, optimizer_method="min_volatility")

        implied = result["implied_returns"]
        posterior = result["posterior_returns"]
        # A: implied ~7.8%, view says 5.0%  → posterior < implied
        # B: implied ~15.6%, view says -3.0% → posterior < implied
        assert isinstance(posterior, pd.Series)
        assert list(posterior.index) == ["A", "B", "C"]
        assert posterior["A"] < implied["A"]
        assert posterior["B"] < implied["B"]

    def test_empty_views_returns_implied(self, market_data):
        weights, cov = market_data
        alloc = BlackLittermanAllocator(weights, cov, tau=0.05)
        result = alloc.allocate([])
        implied = result["implied_returns"]
        posterior = result["posterior_returns"]
        assert np.allclose(posterior.values, implied.values, atol=1e-8)

    def test_zero_confidence_view(self, market_data):
        weights, cov = market_data
        views = [MarketView(ticker="A", direction="bullish", confidence=0.0, magnitude=100.0)]
        alloc = BlackLittermanAllocator(weights, cov, tau=0.05)
        result = alloc.allocate(views)
        implied = result["implied_returns"]
        posterior = result["posterior_returns"]
        assert np.allclose(posterior.values, implied.values, atol=1e-4)

    def test_single_asset(self):
        weights = {"A": 1.0}
        cov = pd.DataFrame([[0.04]], index=["A"], columns=["A"])
        # implied return = delta * 0.04 ≈ 14.2%, so use magnitude > that
        views = [MarketView(ticker="A", direction="bullish", confidence=0.9, magnitude=20.0)]
        alloc = BlackLittermanAllocator(weights, cov, tau=0.05)
        result = alloc.allocate(views)
        assert abs(result["weights"]["A"] - 1.0) < 1e-6
        assert result["posterior_returns"]["A"] > result["implied_returns"]["A"]


class TestMeanVarianceOptimizer:
    @pytest.fixture
    def optimizer(self):
        mu = np.array([0.12, 0.08, 0.06])
        Sigma = np.array([[0.04, 0.01, 0.01], [0.01, 0.09, 0.02], [0.01, 0.02, 0.06]])
        tickers = ["A", "B", "C"]
        return MeanVarianceOptimizer(mu, Sigma, tickers, risk_free_rate=0.0)

    def test_max_sharpe_portfolio(self, optimizer):
        result = optimizer.max_sharpe()
        weights = result["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-4
        assert all(v >= -1e-6 for v in weights.values())
        assert result["sharpe"] > 0

    def test_min_volatility_portfolio(self, optimizer):
        result = optimizer.min_volatility()
        weights = result["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-4
        assert result["volatility"] > 0

    def test_target_return(self, optimizer):
        result = optimizer.target_return(0.09)
        weights = result["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-4
        assert abs(result["return"] - 0.09) < 1e-2

    def test_efficient_frontier(self, optimizer):
        ef = optimizer.efficient_frontier(points=10)
        assert len(ef) > 0
        assert "volatility" in ef.columns
        assert "return" in ef.columns

    def test_optimize_dispatch(self, optimizer):
        r1 = optimizer.optimize("max_sharpe")
        r2 = optimizer.optimize("min_volatility")
        assert r1["sharpe"] >= r2["sharpe"]


class TestRebalancingEngineIntegration:
    def test_black_litterman_rebalance_no_views(self, db_session):
        engine = RebalancingEngine()
        plan = engine.black_litterman_rebalance(db_session, user_id=1, views=None)
        assert plan.total_trades == 0

    def test_black_litterman_rebalance_with_views(self, db_session):
        inst_a = Instrument(ticker="A", full_name="Asset A", sector="Tech")
        inst_b = Instrument(ticker="B", full_name="Asset B", sector="Finance")
        db_session.add_all([inst_a, inst_b])
        db_session.flush()

        db_session.add(Portfolio(instrument_id=inst_a.id, quantity=100, user_id=1))
        db_session.add(Portfolio(instrument_id=inst_b.id, quantity=100, user_id=1))
        db_session.add(Price(instrument_id=inst_a.id, close=100.0, date=date.today()))
        db_session.add(Price(instrument_id=inst_b.id, close=100.0, date=date.today()))
        db_session.commit()

        views = [
            MarketView(ticker="A", direction="bullish", confidence=0.8, magnitude=5.0),
            MarketView(ticker="B", direction="bearish", confidence=0.6, magnitude=-3.0),
        ]
        engine = RebalancingEngine(rebalance_threshold=0.01)
        plan = engine.black_litterman_rebalance(db_session, user_id=1, views=views)

        assert plan.portfolio_value == 20000.0
        assert plan.total_trades >= 0


class TestMarketView:
    def test_dataclass_defaults(self):
        v = MarketView(ticker="SBER", direction="bullish", confidence=0.8, magnitude=5.0)
        assert v.direction == ViewDirection.BULLISH
        assert 0 <= v.confidence <= 1

    def test_confidence_clamped(self):
        v = MarketView(ticker="SBER", direction="bearish", confidence=1.5, magnitude=5.0)
        assert v.confidence == 1.0

    def test_direction_enum_parsing(self):
        v = MarketView(ticker="A", direction=ViewDirection.NEUTRAL, confidence=0.5, magnitude=0.0)
        assert v.direction == ViewDirection.NEUTRAL


class TestEdgeCases:
    def test_all_views_same_ticker(self, market_data):
        weights, cov = market_data
        views = [
            MarketView(ticker="A", direction="bullish", confidence=0.7, magnitude=5.0),
            MarketView(ticker="A", direction="bearish", confidence=0.5, magnitude=-2.0),
        ]
        alloc = BlackLittermanAllocator(weights, cov, tau=0.05)
        result = alloc.allocate(views)
        assert "weights" in result
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-4

    def test_full_confidence_deterministic(self, market_data):
        weights, cov = market_data
        views = [MarketView(ticker="A", direction="bullish", confidence=1.0, magnitude=10.0)]
        alloc = BlackLittermanAllocator(weights, cov, tau=0.05)
        result = alloc.allocate(views)
        posterior = result["posterior_returns"]
        assert posterior["A"] > result["implied_returns"]["A"]
