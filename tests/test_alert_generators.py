from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.alerts.generators import (
    generate_bond_maturity_alerts,
    generate_corporate_event_alerts,
    generate_report_anomalies,
    generate_signal_drop_alerts,
    store_alerts,
)
from src.db.models import (
    AlertLog,
    BondOffering,
    CorporateEvent,
    FinancialReport,
    Instrument,
    Signal,
)


@pytest.fixture(autouse=True)
def _clean_db(db_session):
    db_session.query(AlertLog).delete()
    db_session.query(BondOffering).delete()
    db_session.query(CorporateEvent).delete()
    db_session.query(FinancialReport).delete()
    db_session.query(Signal).delete()
    db_session.query(Instrument).delete()
    db_session.commit()


class TestBondMaturityAlerts:
    def test_no_alerts_when_no_bonds(self, db_session):
        result = generate_bond_maturity_alerts(db_session)
        assert result == []

    def test_alerts_for_near_maturity(self, db_session):
        inst = Instrument(ticker="SU26238RMFS4", full_name="OFZ 26238", instrument_type="bond")
        db_session.add(inst)
        db_session.flush()

        db_session.add(
            BondOffering(
                instrument_id=inst.id,
                offering_date=date.today() - timedelta(days=30),
                maturity_date=date.today() + timedelta(days=5),
                coupon_type="fixed",
                coupon_rate=7.5,
                yield_to_maturity=6.8,
            )
        )
        db_session.commit()

        result = generate_bond_maturity_alerts(db_session, days_threshold=30)
        assert len(result) == 1
        assert result[0]["ticker"] == "SU26238RMFS4"
        assert result[0]["alert_type"] == "bond_maturity"
        assert result[0]["severity"] >= 0.5


class TestReportAnomalies:
    def test_no_alerts_when_no_reports(self, db_session):
        result = generate_report_anomalies(db_session)
        assert result == []

    def test_anomaly_on_negative_profit(self, db_session):
        inst = Instrument(ticker="SBER", full_name="Sberbank")
        db_session.add(inst)
        db_session.flush()

        from datetime import datetime
        today = date.today()
        current = FinancialReport(
            instrument_id=inst.id, report_date=today - timedelta(days=30),
            period_type="FY", net_profit=-5_000_000_000, revenue=100_000_000_000,
        )
        prev = FinancialReport(
            instrument_id=inst.id, report_date=today - timedelta(days=400),
            period_type="FY", net_profit=10_000_000_000, revenue=100_000_000_000,
        )
        db_session.add_all([current, prev])
        db_session.commit()

        result = generate_report_anomalies(db_session)

        assert len(result) >= 1
        assert result[0]["alert_type"] == "report_anomaly"


class TestCorporateEventAlerts:
    def test_no_events(self, db_session):
        result = generate_corporate_event_alerts(db_session)
        assert result == []

    def test_upcoming_divident_alert(self, db_session):
        inst = Instrument(ticker="LKOH", full_name="Lukoil")
        db_session.add(inst)
        db_session.flush()

        db_session.add(
            CorporateEvent(
                instrument_id=inst.id, event_type="dividend",
                announcement_date=date.today() + timedelta(days=3),
                description="Dividend record date",
            )
        )
        db_session.commit()

        result = generate_corporate_event_alerts(db_session, days_ahead=14)
        assert len(result) == 1
        assert result[0]["ticker"] == "LKOH"
        assert result[0]["alert_type"] == "corporate_event"


class TestSignalDropAlerts:
    def test_no_signals(self, db_session):
        result = generate_signal_drop_alerts(db_session)
        assert result == []

    def test_signal_drop_detected(self, db_session):
        inst = Instrument(ticker="SBER", full_name="Sberbank")
        db_session.add(inst)
        db_session.flush()

        from datetime import datetime, timedelta as dt_td
        today = date.today()
        # conf goes 0.8 → 0.3 → 0.85 → 0.35: yesterday=0.3 < threshold from 0.8
        for i, conf in enumerate([0.3, 0.8, 0.35, 0.85]):
            db_session.add(
                Signal(
                    instrument_id=inst.id, confidence=conf, action="BUY",
                    date=datetime(today.year, today.month, today.day, 12, 0) - dt_td(days=i),
                )
            )
        db_session.commit()

        result = generate_signal_drop_alerts(db_session, drop_threshold=0.3)

        assert len(result) >= 1
        assert result[0]["alert_type"] == "signal_drop"


class TestStoreAlerts:
    def test_store_and_deduplicate(self, db_session):
        alerts = [
            {"ticker": "SBER", "alert_type": "signal_drop", "severity": 0.5, "title": "Drop", "message": "test", "metadata": {}},
        ]
        stored = store_alerts(db_session, alerts)
        assert stored == 1

        count = db_session.query(AlertLog).count()
        assert count == 1

        stored2 = store_alerts(db_session, alerts)
        assert stored2 == 0
