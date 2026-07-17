"""Tests for bond ladder and duration matching."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from src.analysis.rebalancing import BondLadderPlan, build_bond_ladder, duration_match_portfolio


class MockBondOffering:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        for attr in ("yield_to_maturity", "coupon_rate", "credit_rating", "duration_years"):
            if attr not in kwargs:
                setattr(self, attr, None)


class TestBuildBondLadder:
    def test_empty_db_returns_empty(self):
        db = MagicMock()
        db.query().join().filter().order_by().limit().all.return_value = []
        plan = build_bond_ladder(db)
        assert isinstance(plan, BondLadderPlan)
        assert plan.rungs == []
        assert plan.actual_duration == 0.0

    def test_single_bond_ladder(self):
        db = MagicMock()
        mock_bond = MockBondOffering(
            maturity_date=date.today() + timedelta(days=365),
            duration_years=0.8,
            yield_to_maturity=12.0,
            coupon_rate=11.0,
            credit_rating="AAA",
            instrument_id=1,
        )
        mock_instr = MagicMock(id=1, ticker="SU26238")
        db.query().join().filter().order_by().limit().all.return_value = [mock_bond]
        db.query().filter.return_value.all.return_value = [mock_instr]

        plan = build_bond_ladder(db, target_duration=2.0)
        assert len(plan.rungs) == 1
        assert plan.rungs[0].bucket == "short"
        assert plan.rungs[0].ticker == "SU26238"
        assert plan.actual_duration == 0.8
        assert plan.target_duration == 2.0
        assert plan.duration_gap == 1.2

    def test_bonds_bucketed_correctly(self):
        db = MagicMock()
        now = date.today()
        bonds = [
            MockBondOffering(maturity_date=now + timedelta(days=365), duration_years=0.9, instrument_id=1),
            MockBondOffering(maturity_date=now + timedelta(days=365 * 3), duration_years=2.5, instrument_id=2),
            MockBondOffering(maturity_date=now + timedelta(days=365 * 7), duration_years=5.5, instrument_id=3),
        ]
        db.query().join().filter().order_by().limit().all.return_value = bonds

        instrs = [MagicMock(id=i+1, ticker=f"BOND{i}") for i in range(3)]
        db.query().filter.return_value.all.return_value = instrs

        plan = build_bond_ladder(db)
        assert len(plan.rungs) == 3
        assert plan.rungs[0].bucket == "short"
        assert plan.rungs[1].bucket == "mid"
        assert plan.rungs[2].bucket == "long"


class TestDurationMatchPortfolio:
    def test_empty_db_returns_empty(self):
        db = MagicMock()
        db.query().join().filter().all.return_value = []
        result = duration_match_portfolio(db, portfolio_value=100_000)
        assert result == []

    def test_candidates_sorted_by_score(self):
        db = MagicMock()
        bonds = [
            MockBondOffering(duration_years=3.0, yield_to_maturity=12.0, credit_rating="AAA", instrument_id=1),
            MockBondOffering(duration_years=5.0, yield_to_maturity=8.0, credit_rating="BBB", instrument_id=2),
        ]
        db.query().join().filter().all.return_value = bonds
        instrs = [MagicMock(id=1, ticker="SU26238"), MagicMock(id=2, ticker="CORP01")]
        db.query().filter.return_value.all.return_value = instrs

        result = duration_match_portfolio(db, portfolio_value=100_000)
        assert len(result) == 2
        assert result[0]["score"] >= result[1]["score"]

    def test_zero_duration_skipped(self):
        db = MagicMock()
        bonds = [
            MockBondOffering(duration_years=0, instrument_id=1),
            MockBondOffering(duration_years=None, instrument_id=2),
        ]
        db.query().join().filter().all.return_value = bonds
        result = duration_match_portfolio(db, portfolio_value=100_000)
        assert result == []
