from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCBRSource:
    @pytest.mark.asyncio
    async def test_fetch_returns_rates(self):
        from src.collectors.alternative import CBRSource

        xml_data = """<?xml version="1.0"?>
<ValCurs>
  <Valute>
    <CharCode>USD</CharCode>
    <NumCode>840</NumCode>
    <Value>75,50</Value>
  </Valute>
  <Valute>
    <CharCode>EUR</CharCode>
    <NumCode>978</NumCode>
    <Value>85,20</Value>
  </Valute>
  <Valute>
    <CharCode>CNY</CharCode>
    <NumCode>156</NumCode>
    <Value>11,30</Value>
  </Valute>
</ValCurs>"""

        mock_response = MagicMock()
        mock_response.content = xml_data.encode("utf-8")
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(CBRSource, "_get_client", return_value=mock_client):
            source = CBRSource()
            result = await source.fetch()

        assert "rates" in result
        assert len(result["rates"]) == 3

        usd = [r for r in result["rates"] if r["indicator_name"] == "cbr_USD/RUB"][0]
        assert usd["value"] == 75.5

        eur = [r for r in result["rates"] if r["indicator_name"] == "cbr_EUR/RUB"][0]
        assert eur["value"] == 85.2

        cny = [r for r in result["rates"] if r["indicator_name"] == "cbr_CNY/RUB"][0]
        assert cny["value"] == 11.3

    @pytest.mark.asyncio
    async def test_fetch_handles_http_error(self):
        from src.collectors.alternative import CBRSource

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("HTTP error")

        with patch.object(CBRSource, "_get_client", return_value=mock_client):
            source = CBRSource()
            result = await source.fetch()

        assert result == {"rates": []}

    @pytest.mark.asyncio
    async def test_fetch_skips_unknown_currencies(self):
        from src.collectors.alternative import CBRSource

        xml_data = """<?xml version="1.0"?>
<ValCurs>
  <Valute>
    <CharCode>GBP</CharCode>
    <Value>99,99</Value>
  </Valute>
</ValCurs>"""

        mock_response = MagicMock()
        mock_response.content = xml_data.encode("utf-8")
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(CBRSource, "_get_client", return_value=mock_client):
            source = CBRSource()
            result = await source.fetch()

        assert result == {"rates": []}


class TestRosstatSource:
    @pytest.mark.asyncio
    async def test_fetch_returns_indicators(self):
        from src.collectors.alternative import RosstatSource

        mock_client = AsyncMock()

        async def side_effect(url: str) -> MagicMock:
            resp = MagicMock()
            if "gdp" in url:
                resp.json.return_value = {"value": 1.5}
            elif "inflation" in url:
                resp.json.return_value = {"value": 4.2}
            elif "unemployment" in url:
                resp.json.return_value = {"value": 3.8}
            else:
                resp.json.return_value = {}
            resp.raise_for_status.return_value = None
            return resp

        mock_client.get.side_effect = side_effect

        with patch.object(RosstatSource, "_get_client", return_value=mock_client):
            source = RosstatSource()
            result = await source.fetch()

        assert "indicators" in result
        assert len(result["indicators"]) == 3

        names = {r["indicator_name"] for r in result["indicators"]}
        assert names == {"rosstat_gdp", "rosstat_inflation", "rosstat_unemployment"}

    @pytest.mark.asyncio
    async def test_fetch_handles_http_failure_gracefully(self):
        from src.collectors.alternative import RosstatSource

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection error")

        with patch.object(RosstatSource, "_get_client", return_value=mock_client):
            source = RosstatSource()
            result = await source.fetch()

        assert "indicators" in result
        assert result["indicators"] == []


class TestGoogleTrendsSource:
    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_pytrends_missing(self):
        from src.collectors.alternative import GoogleTrendsSource

        with patch("src.collectors.alternative.GoogleTrendsSource._init_pytrends"):
            source = GoogleTrendsSource()
            source._trends_available = False
            result = await source.fetch()

        assert result == {"trends": []}


class TestAlternativeDataCollector:
    @pytest.mark.asyncio
    async def test_fetch_all_returns_dict_with_source_keys(self):
        from src.collectors.alternative import AlternativeDataCollector, CBRSource, GoogleTrendsSource, RosstatSource

        cbr = MagicMock(spec=CBRSource)
        cbr.name = "cbr"
        cbr.fetch.return_value = {"rates": [{"indicator_name": "cbr_USD/RUB", "value": 75.0, "date": date.today()}]}

        rosstat = MagicMock(spec=RosstatSource)
        rosstat.name = "rosstat"
        rosstat.fetch.return_value = {
            "indicators": [{"indicator_name": "rosstat_gdp", "value": 1.5, "date": date.today()}]
        }

        trends = MagicMock(spec=GoogleTrendsSource)
        trends.name = "google_trends"
        trends.fetch.return_value = {"trends": []}

        collector = AlternativeDataCollector(sources=[cbr, rosstat, trends])
        result = await collector.fetch_all()

        assert "rates" in result
        assert "indicators" in result
        assert "trends" in result
        assert len(result["rates"]) == 1
        assert len(result["indicators"]) == 1

    @pytest.mark.asyncio
    async def test_fetch_all_handles_source_failure(self):
        from src.collectors.alternative import AlternativeDataCollector, CBRSource

        failing_source = MagicMock(spec=CBRSource)
        failing_source.name = "broken"
        failing_source.fetch.side_effect = Exception("Broken source")

        collector = AlternativeDataCollector(sources=[failing_source])
        result = await collector.fetch_all()

        assert "broken" in result

    @pytest.mark.asyncio
    async def test_store_to_db_creates_alt_data_points(self):
        from src.collectors.alternative import AlternativeDataCollector
        from src.db.models import AltDataPoint

        db = MagicMock()
        collector = AlternativeDataCollector(sources=[])

        data = {
            "rates": [
                {"indicator_name": "cbr_USD/RUB", "value": 75.0, "date": date.today()},
                {"indicator_name": "cbr_EUR/RUB", "value": 85.0, "date": date.today()},
            ]
        }
        points = await collector.store_to_db(db, data)

        assert len(points) == 2
        assert all(isinstance(p, AltDataPoint) for p in points)
        assert db.add.call_count == 2
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_to_db_rollback_on_failure(self):
        from src.collectors.alternative import AlternativeDataCollector

        db = MagicMock()
        db.commit.side_effect = Exception("DB error")
        collector = AlternativeDataCollector(sources=[])

        data = {
            "rates": [
                {"indicator_name": "cbr_USD/RUB", "value": 75.0, "date": date.today()},
            ]
        }
        points = await collector.store_to_db(db, data)

        assert points == []
        db.rollback.assert_called_once()
