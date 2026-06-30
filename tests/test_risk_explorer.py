from __future__ import annotations

from datetime import date

import pytest

from src.db.models import Instrument, Portfolio, Price


@pytest.fixture(autouse=True)
def _clean_db(db_session):
    db_session.query(Portfolio).delete()
    db_session.query(Price).delete()
    db_session.query(Instrument).delete()
    db_session.commit()


class TestRiskExplorerIntegration:
    def test_portfolio_risk_empty(self, db_session):
        from src.analysis.risk_explorer import RiskExplorer

        explorer = RiskExplorer()
        result = explorer.portfolio_risk_summary(db_session, user_id=1)
        assert "sector_concentration" in result
        assert result["VaR_95"] == 0.0

    def test_portfolio_risk_with_positions(self, db_session):
        from src.analysis.risk_explorer import RiskExplorer

        inst = Instrument(ticker="SBER", full_name="Sberbank", sector="Finance")
        db_session.add(inst)
        db_session.flush()

        db_session.add(Portfolio(instrument_id=inst.id, quantity=100, avg_price=250.0, user_id=1))
        for i in range(30):
            db_session.add(Price(instrument_id=inst.id, close=250.0 + i, date=date(2024, 1, i + 1)))
        db_session.commit()

        explorer = RiskExplorer()
        result = explorer.portfolio_risk_summary(db_session, user_id=1)

        assert "sector_concentration" in result
        assert "VaR_95" in result

    def test_ticker_deep_dive(self, db_session):
        from src.analysis.risk_explorer import RiskExplorer

        inst = Instrument(ticker="GAZP", full_name="Gazprom", sector="Energy")
        db_session.add(inst)
        db_session.flush()

        for i in range(30):
            db_session.add(Price(instrument_id=inst.id, close=200.0 - i * 0.5, date=date(2024, 1, i + 1)))
        db_session.commit()

        explorer = RiskExplorer()
        result = explorer.ticker_deep_dive(db_session, "GAZP")

        assert "price_stats" in result
        assert "volatility" in result["price_stats"]
