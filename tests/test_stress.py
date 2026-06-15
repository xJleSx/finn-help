from __future__ import annotations

import pytest

from src.analysis.stress import (
    CRASH_SCENARIOS,
    SECTOR_SHOCKS,
    StressTester,
    format_portfolio_for_stress,
)


def _sample_positions():
    return [
        {"ticker": "SBER", "amount": 50000, "last_price": 287.0, "sector": "Финансы", "name": "Сбер"},
        {"ticker": "GAZP", "amount": 30000, "last_price": 165.0, "sector": "Нефть", "name": "Газпром"},
        {"ticker": "LKOH", "amount": 20000, "last_price": 7100.0, "sector": "Нефть", "name": "Лукойл"},
    ]


class TestStressFormatters:
    def test_format_empty(self):
        assert format_portfolio_for_stress({}) == []

    def test_format_with_plan(self):
        plan = {
            "etf": {
                "items": [{"ticker": "FXUS", "amount": 40000, "name": "Акции США"}],
            },
            "bond": {
                "items": [{"ticker": "SU26238RMFS5", "amount": 20000, "name": "ОФЗ"}],
            },
        }
        positions = format_portfolio_for_stress(plan)
        assert len(positions) >= 2


class TestStressTester:
    @pytest.fixture
    def tester(self):
        return StressTester(_sample_positions())

    def test_total_calculated(self, tester):
        assert tester.total == pytest.approx(100_000)

    def test_run_crash_scenarios(self, tester):
        results = tester.run_crash_scenarios()
        assert len(results) == len(CRASH_SCENARIOS)
        for r in results:
            assert "scenario" in r
            assert "loss" in r
            assert "loss_pct" in r
            assert r["loss"] <= 0

    def test_run_sector_shocks(self, tester):
        results = tester.run_sector_shocks()
        assert len(results) == len(SECTOR_SHOCKS)
        for r in results:
            assert "scenario" in r
            assert "loss" in r

    def test_run_custom_shock_exists(self, tester):
        result = tester.run_custom_shock("SBER", -0.3)
        assert result is not None
        assert "details" in result
        assert result["details"][0]["ticker"] == "SBER"
        assert result["details"][0]["change_pct"] == pytest.approx(-0.3)
        assert result["loss"] == pytest.approx(-15_000)
        assert result["total_after"] == pytest.approx(85_000)

    def test_run_custom_shock_missing(self, tester):
        result = tester.run_custom_shock("NONEXIST", -0.5)
        assert result is None

    def test_format_results_contains_scenario_names(self, tester):
        results = tester.run_crash_scenarios()
        text = tester.format_results(results)
        assert len(text) > 0

    def test_worst_historical_period(self, tester):
        prices = [100 + i + (i % 20) * 10 for i in range(100)]
        result = tester.worst_historical_period(prices, window=10)
        assert "max_drawdown" in result
        assert "worst_period" in result
        assert result["max_drawdown"] < 0
