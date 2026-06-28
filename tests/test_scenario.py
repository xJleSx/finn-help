from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.analysis.scenario.engine import ScenarioEngine, ScenarioResult
from src.db.models import Base, Instrument, Portfolio, Price


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def db_with_positions(db_session: Session) -> Session:
    inst1 = Instrument(id=1, ticker="SBER", sector="Банки", full_name="Sberbank")
    inst2 = Instrument(id=2, ticker="GAZP", sector="Нефть и газ", full_name="Gazprom")
    inst3 = Instrument(id=3, ticker="LKOH", sector="Нефть и газ", full_name="Lukoil")
    db_session.add_all([inst1, inst2, inst3])
    db_session.flush()

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for inst_id in [1, 2, 3]:
        for i in range(252):
            day = base + timedelta(days=i)
            db_session.add(Price(
                instrument_id=inst_id, date=day.date(),
                open=100.0 + i * 0.1 + np.random.normal(0, 1),
                close=100.0 + i * 0.1 + np.random.normal(0, 1),
                volume=1000,
            ))

    db_session.add(Portfolio(user_id=1, instrument_id=1, quantity=100, avg_price=250.0))
    db_session.add(Portfolio(user_id=1, instrument_id=2, quantity=50, avg_price=150.0))
    db_session.add(Portfolio(user_id=2, instrument_id=3, quantity=200, avg_price=3000.0))
    db_session.commit()
    return db_session


# --- ScenarioResult ---

class TestScenarioResult:
    def test_defaults(self):
        r = ScenarioResult(name="test")
        assert r.name == "test"
        assert r.loss_pct == 0.0
        assert r.details == []
        assert r.scenario_type == "shock"


# --- ScenarioEngine ---

class TestScenarioEngineFromPortfolio:
    def test_from_portfolio(self, db_with_positions: Session):
        engine = ScenarioEngine().from_portfolio(db_with_positions, user_id=1)
        assert len(engine.positions) == 2
        assert engine._total > 0

    def test_from_portfolio_empty_user(self, db_with_positions: Session):
        engine = ScenarioEngine().from_portfolio(db_with_positions, user_id=999)
        assert engine.positions == []
        assert engine._total == 0.0

    def test_from_portfolio_user2(self, db_with_positions: Session):
        engine = ScenarioEngine().from_portfolio(db_with_positions, user_id=2)
        assert len(engine.positions) == 1
        assert engine.positions[0]["ticker"] == "LKOH"


class TestScenarioEngineFromPositions:
    def test_from_positions_dict(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "sector": "Банки", "quantity": 100, "avg_price": 250},
            {"ticker": "GAZP", "sector": "Нефть и газ", "quantity": 50, "avg_price": 150},
        ])
        assert len(engine.positions) == 2
        assert engine._total == 32500.0

    def test_from_positions_with_amount(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "amount": 25000},
            {"ticker": "GAZP", "amount": 7500},
        ])
        assert engine._total == 32500.0

    def test_from_positions_empty(self):
        engine = ScenarioEngine().from_positions([])
        assert engine.positions == []
        assert engine._total == 0.0


class TestScenarioEngineLoadPrices:
    def test_load_prices(self, db_with_positions: Session):
        engine = ScenarioEngine().from_portfolio(db_with_positions, user_id=1)
        engine.load_prices(db_with_positions, days_back=365)
        assert len(engine._tickers) > 0
        assert engine._cov_matrix is not None
        assert engine._weights is not None

    def test_load_prices_no_positions(self, db_session: Session):
        engine = ScenarioEngine().from_portfolio(db_session, user_id=999)
        engine.load_prices(db_session)
        assert engine._cov_matrix is None


class TestScenarioEngineRunScenario:
    def test_run_scenario_overall(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "amount": 30000},
            {"ticker": "GAZP", "amount": 20000},
        ])
        result = engine.run_scenario("Test Crash", {"overall": -0.30})
        assert result.name == "Test Crash"
        assert result.total_before == 50000.0
        assert result.total_after == 35000.0
        assert result.loss == -15000.0
        assert result.loss_pct == -0.3
        assert len(result.details) == 2

    def test_run_scenario_sector_specific(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "sector": "Банки", "amount": 30000},
            {"ticker": "GAZP", "sector": "Нефть и газ", "amount": 20000},
        ])
        result = engine.run_scenario("Oil shock", {
            "Нефть и газ": -0.40, "overall": -0.10,
        })
        assert result.total_before == 50000.0
        assert result.total_after == pytest.approx(
            30000 * 0.9 + 20000 * 0.6
        )

    def test_run_crash_scenarios(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "sector": "Банки", "amount": 50000},
        ])
        results = engine.run_crash_scenarios()
        assert len(results) == 4
        for r in results:
            assert r.loss <= 0

    def test_run_macro_scenarios(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "amount": 50000},
        ])
        results = engine.run_macro_scenarios()
        assert len(results) == 5


class TestScenarioEngineCustomShock:
    def test_custom_ticker_shock(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "sector": "Банки", "amount": 40000},
            {"ticker": "GAZP", "sector": "Нефть и газ", "amount": 10000},
        ])
        result = engine.run_custom_shock("SBER", -0.20)
        assert result is not None
        assert result.name == "SBER: -20%"
        assert result.loss == -8000.0

    def test_custom_ticker_shock_unknown(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "amount": 40000},
        ])
        result = engine.run_custom_shock("UNKNOWN", -0.20)
        assert result is None

    def test_custom_sector_shock(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "sector": "Банки", "amount": 30000},
            {"ticker": "VTBR", "sector": "Банки", "amount": 20000},
            {"ticker": "GAZP", "sector": "Нефть и газ", "amount": 50000},
        ])
        result = engine.run_custom_sector_shock("Банки", -0.25)
        assert result.loss == pytest.approx(-12500.0)


class TestScenarioEngineMonteCarlo:
    def test_monte_carlo_no_data(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "amount": 50000},
        ])
        result = engine.run_monte_carlo(n_simulations=100)
        assert result.name == "Monte Carlo"
        assert result.loss_pct == 0.0  # no cov matrix

    def test_monte_carlo_with_data(self, db_with_positions: Session):
        engine = (
            ScenarioEngine()
            .from_portfolio(db_with_positions, user_id=1)
            .load_prices(db_with_positions, days_back=365)
        )
        result = engine.run_monte_carlo(n_simulations=500)
        assert -1.0 <= result.var_95 <= 0.0
        assert -1.0 <= result.cvar_95 <= 0.0
        assert result.var_99 <= result.var_95


class TestScenarioEngineBootstrap:
    def test_bootstrap_no_data(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "amount": 50000},
        ])
        result = engine.run_historical_bootstrap(n_simulations=100)
        assert result.loss_pct == 0.0

    def test_bootstrap_with_data(self, db_with_positions: Session):
        engine = (
            ScenarioEngine()
            .from_portfolio(db_with_positions, user_id=1)
            .load_prices(db_with_positions, days_back=365)
        )
        result = engine.run_historical_bootstrap(n_simulations=500)
        assert -1.0 <= result.var_95 <= 0.0


class TestScenarioEngineRunAll:
    def test_run_all(self, db_with_positions: Session):
        engine = (
            ScenarioEngine()
            .from_portfolio(db_with_positions, user_id=1)
            .load_prices(db_with_positions, days_back=365)
        )
        results = engine.run_all()
        assert "total" in results
        assert "scenarios" in results
        assert "monte_carlo" in results
        assert "bootstrap" in results
        assert "sector_breakdown" in results
        assert len(results["scenarios"]) > 0

    def test_run_all_no_prices(self):
        engine = ScenarioEngine().from_positions([
            {"ticker": "SBER", "amount": 50000},
        ])
        results = engine.run_all()
        assert results["total"] == 50000.0
        assert results["monte_carlo"]["var_95"] == 0.0


class TestScenarioEngineMaxDrawdown:
    def test_max_drawdown(self, db_with_positions: Session):
        engine = ScenarioEngine()
        result = engine.max_drawdown(db_with_positions, "SBER", window=100)
        assert "ticker" in result
        assert "max_drawdown" in result
        assert result["ticker"] == "SBER"
        assert result["max_drawdown"] <= 0.0

    def test_max_drawdown_no_data(self, db_session: Session):
        engine = ScenarioEngine()
        result = engine.max_drawdown(db_session, "UNKNOWN")
        assert result["max_drawdown"] == 0.0
