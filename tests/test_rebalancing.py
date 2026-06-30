from __future__ import annotations

from datetime import date

import pytest

from src.analysis.rebalancing import RebalancingEngine
from src.db.models import Instrument, Portfolio, Price


@pytest.fixture(autouse=True)
def _clean_db(db_session):
    db_session.query(Portfolio).delete()
    db_session.query(Price).delete()
    db_session.query(Instrument).delete()
    db_session.commit()


class TestRebalancingEngineIntegration:
    def test_analyze_portfolio_empty(self, db_session):
        engine = RebalancingEngine()
        result = engine.analyze_portfolio(db_session, user_id=1)
        assert result == []

    def test_analyze_portfolio_returns_deviations(self, db_session):
        inst = Instrument(ticker="SBER", full_name="Sberbank", sector="Finance")
        db_session.add(inst)
        db_session.flush()

        db_session.add(Portfolio(instrument_id=inst.id, quantity=100, user_id=1))
        db_session.add(Price(instrument_id=inst.id, close=250.0, date=date.today()))
        db_session.commit()

        engine = RebalancingEngine(rebalance_threshold=0.05)
        result = engine.analyze_portfolio(db_session, user_id=1)

        assert len(result) == 1
        assert result[0]["ticker"] == "SBER"
        assert result[0]["current_weight"] == 1.0
        assert "alerts" in result[0]

    def test_sector_limit_detected(self, db_session):
        stock1 = Instrument(ticker="SBER", full_name="Sberbank", sector="Finance")
        stock2 = Instrument(ticker="VTBR", full_name="VTB", sector="Finance")
        db_session.add_all([stock1, stock2])
        db_session.flush()

        db_session.add(Portfolio(instrument_id=stock1.id, quantity=100, user_id=1))
        db_session.add(Portfolio(instrument_id=stock2.id, quantity=100, user_id=1))
        db_session.add(Price(instrument_id=stock1.id, close=300.0, date=date.today()))
        db_session.add(Price(instrument_id=stock2.id, close=200.0, date=date.today()))
        db_session.commit()

        engine = RebalancingEngine(max_sector_pct=0.35)
        result = engine.analyze_portfolio(db_session, user_id=1)

        finance_weight = sum(r["current_weight"] for r in result)
        assert finance_weight > 0.35
