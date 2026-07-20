from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

# ── WorldBankCollector tests ─────────────────────────────────────────────


class TestWorldBankCollector:
    @pytest.mark.asyncio
    async def test_fetch_gdp_parses_response(self):
        from src.geo.world_bank import WorldBankCollector

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"page": 1, "pages": 1, "per_page": 10, "total": 2},
            [
                {"date": "2023", "value": 1_500_000_000_000},
                {"date": "2022", "value": 1_400_000_000_000},
            ],
        ]
        mock_client.get.return_value = mock_resp

        collector = WorldBankCollector(client=mock_client)
        result = await collector.fetch_gdp("RU", years=2)

        assert len(result) == 2
        assert result[0]["year"] == "2023"
        assert result[0]["value"] == 1_500_000_000_000
        assert result[0]["indicator"] == "NY.GDP.MKTP.CD"

    @pytest.mark.asyncio
    async def test_fetch_inflation_parses_response(self):
        from src.geo.world_bank import WorldBankCollector

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"page": 1, "pages": 1, "per_page": 10, "total": 1},
            [{"date": "2023", "value": 7.42}],
        ]
        mock_client.get.return_value = mock_resp

        collector = WorldBankCollector(client=mock_client)
        result = await collector.fetch_inflation("RU")

        assert len(result) == 1
        assert result[0]["value"] == 7.42

    @pytest.mark.asyncio
    async def test_fetch_unemployment_parses_response(self):
        from src.geo.world_bank import WorldBankCollector

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"page": 1, "pages": 1, "per_page": 10, "total": 1},
            [{"date": "2023", "value": 3.2}],
        ]
        mock_client.get.return_value = mock_resp

        collector = WorldBankCollector(client=mock_client)
        result = await collector.fetch_unemployment("RU")

        assert len(result) == 1
        assert result[0]["value"] == 3.2

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self):
        from src.geo.world_bank import WorldBankCollector

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.HTTPStatusError("404", request=AsyncMock(), response=AsyncMock(status_code=404))

        collector = WorldBankCollector(client=mock_client)
        result = await collector.fetch_gdp("XX")

        assert result == []

    @pytest.mark.asyncio
    async def test_malformed_json_returns_empty_list(self):
        from src.geo.world_bank import WorldBankCollector

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("bad json")
        mock_client.get.return_value = mock_resp

        collector = WorldBankCollector(client=mock_client)
        result = await collector.fetch_gdp("RU")

        assert result == []

    @pytest.mark.asyncio
    async def test_no_data_for_country_returns_empty_list(self):
        from src.geo.world_bank import WorldBankCollector

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"page": 1, "pages": 1, "per_page": 10, "total": 0}]
        mock_client.get.return_value = mock_resp

        collector = WorldBankCollector(client=mock_client)
        result = await collector.fetch_gdp("XX")

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_sanctions_risk_returns_results(self):
        from src.geo.world_bank import WorldBankCollector

        mock_client = AsyncMock(spec=httpx.AsyncClient)

        def mock_sanctions_response(*args, **kwargs):
            resp = AsyncMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "ok", "totalResults": 150}
            return resp

        mock_client.get.side_effect = mock_sanctions_response

        collector = WorldBankCollector(client=mock_client)
        results = await collector.fetch_sanctions_risk()

        assert len(results) > 0
        assert all(r["source"] == "newsapi" for r in results)
        assert results[0]["total_results"] == 150


# ── BayesianGeoRisk tests ─────────────────────────────────────────────────


class TestBayesianPrior:
    def setup_method(self):
        from src.geo.bayesian_risk import BayesianGeoRisk

        self.model = BayesianGeoRisk()

    def test_prior_mean_is_low(self):
        risk = self.model.get_risk("RU")
        expected = 2.0 / (2.0 + 20.0)
        assert risk == pytest.approx(expected)

    def test_prior_risk_level_is_low(self):
        assert self.model.get_risk_level("RU") == "LOW"


class TestBayesianUpdate:
    def setup_method(self):
        from src.geo.bayesian_risk import BayesianGeoRisk

        self.model = BayesianGeoRisk()

    def test_bullish_evidence_decreases_risk(self):
        prior = self.model.get_risk("RU")
        self.model.update("RU", {"type": "macro", "likelihood": 0.01, "observations": 20})
        posterior = self.model.get_risk("RU")
        assert posterior < prior

    def test_bearish_evidence_increases_risk(self):
        prior = self.model.get_risk("RU")
        self.model.update("RU", {"type": "sanctions", "likelihood": 0.9, "observations": 5})
        posterior = self.model.get_risk("RU")
        assert posterior > prior

    def test_update_returns_summary_dict(self):
        result = self.model.update("RU", {"type": "macro", "likelihood": 0.3, "observations": 3})
        assert result["country"] == "RU"
        assert "posterior_mean" in result
        assert result["signal_type"] == "macro"
        assert result["signal_likelihood"] == 0.3


class TestRiskLevelThresholds:
    def setup_method(self):
        from src.geo.bayesian_risk import BayesianGeoRisk, CountryState

        self.model = BayesianGeoRisk()
        self.CountryState = CountryState

    def test_low_below_0_3(self):
        assert self.model.get_risk_level("low_country") == "LOW"
        assert self.model.get_risk("low_country") < 0.3

    def test_moderate_0_3_to_0_6(self):
        self.model._countries["mod_country"] = self.CountryState(alpha=6.0, beta=8.0)
        risk = self.model.get_risk("mod_country")
        assert 0.3 <= risk <= 0.6
        assert self.model.get_risk_level("mod_country") == "MODERATE"

    def test_high_0_6_to_0_8(self):
        self.model._countries["high_country"] = self.CountryState(alpha=12.0, beta=5.0)
        risk = self.model.get_risk("high_country")
        assert 0.6 <= risk <= 0.8
        assert self.model.get_risk_level("high_country") == "HIGH"

    def test_critical_above_0_8(self):
        self.model._countries["crit_country"] = self.CountryState(alpha=30.0, beta=2.0)
        risk = self.model.get_risk("crit_country")
        assert risk > 0.8
        assert self.model.get_risk_level("crit_country") == "CRITICAL"

    def test_high_at_exactly_0_8(self):
        self.model._countries["h80"] = self.CountryState(alpha=8.0, beta=2.0)
        assert self.model.get_risk("h80") == pytest.approx(0.8)
        assert self.model.get_risk_level("h80") == "HIGH"

    def test_edge_case_boundaries(self):
        self.model._countries["c1"] = self.CountryState(alpha=3.0, beta=7.0)
        assert self.model.get_risk("c1") == pytest.approx(0.3)
        assert self.model.get_risk_level("c1") == "MODERATE"

        self.model._countries["c2"] = self.CountryState(alpha=6.0, beta=4.0)
        assert self.model.get_risk("c2") == pytest.approx(0.6)
        assert self.model.get_risk_level("c2") == "HIGH"

        self.model._countries["c3"] = self.CountryState(alpha=8.0, beta=2.0)
        assert self.model.get_risk("c3") == pytest.approx(0.8)
        assert self.model.get_risk_level("c3") == "HIGH"


class TestCombineSignals:
    def setup_method(self):
        from src.geo.bayesian_risk import BayesianGeoRisk

        self.model = BayesianGeoRisk()

    def test_conflicting_signals(self):
        signals = [
            {"type": "sanctions", "likelihood": 0.9, "weight": 5.0},
            {"type": "macro", "likelihood": 0.2, "weight": 5.0},
            {"type": "news", "likelihood": 0.6, "weight": 5.0},
        ]
        fused = self.model.combine_signals("CN", signals)
        assert 0.0 <= fused <= 1.0
        assert fused < 0.5

    def test_empty_signals_returns_current_risk(self):
        risk = self.model.combine_signals("XX", [])
        expected = 2.0 / (2.0 + 20.0)
        assert risk == pytest.approx(expected)

    def test_all_high_signals_drive_risk_up(self):
        signals = [
            {"type": "sanctions", "likelihood": 0.95, "weight": 20.0},
            {"type": "conflict", "likelihood": 0.95, "weight": 20.0},
        ]
        fused = self.model.combine_signals("IR", signals)
        assert fused > 0.5

    def test_all_low_signals_drive_risk_down(self):
        signals = [
            {"type": "trade_deal", "likelihood": 0.01, "weight": 20.0},
            {"type": "diplomacy", "likelihood": 0.01, "weight": 20.0},
        ]
        fused = self.model.combine_signals("CH", signals)
        assert fused < 0.3


class TestBayesianEdgeCases:
    def setup_method(self):
        from src.geo.bayesian_risk import BayesianGeoRisk

        self.model = BayesianGeoRisk()

    def test_no_data_for_country_returns_prior(self):
        risk = self.model.get_risk("nonexistent")
        assert risk == pytest.approx(2.0 / 22.0)

    def test_level_for_unknown_country_is_low(self):
        assert self.model.get_risk_level("unknown") == "LOW"

    def test_update_clamps_likelihood(self):
        result = self.model.update("RU", {"type": "test", "likelihood": 2.0})
        assert result["signal_likelihood"] == pytest.approx(0.99)

        result = self.model.update("RU", {"type": "test", "likelihood": -1.0})
        assert result["signal_likelihood"] == pytest.approx(0.01)

    def test_combine_signals_with_empty_list_does_not_create_state(self):
        from src.geo.bayesian_risk import BayesianGeoRisk

        model = BayesianGeoRisk()
        _ = model.combine_signals("ZZ", [])
        assert "ZZ" not in model._countries


class TestBayesianPersistence:
    def test_load_from_db_no_session_does_not_raise(self):
        from src.geo.bayesian_risk import BayesianGeoRisk

        model = BayesianGeoRisk(db_session=None)
        model.load_from_db()
        assert model.get_risk("any") == pytest.approx(2.0 / 22.0)

    def test_save_to_db_no_session_does_not_raise(self):
        from src.geo.bayesian_risk import BayesianGeoRisk

        model = BayesianGeoRisk(db_session=None)
        model.update("RU", {"type": "macro", "likelihood": 0.3})
        model.save_to_db()
