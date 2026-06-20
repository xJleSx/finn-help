from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCBRCollector:
    @pytest.mark.asyncio
    async def test_get_rates_success(self):
        from src.collectors.cbr import CBRCollector

        xml_data = """<?xml version="1.0"?>
<ValCurs>
  <Valute>
    <CharCode>USD</CharCode>
    <NumCode>840</NumCode>
    <Name>Dollar</Name>
    <VunitRate>75,50</VunitRate>
    <Nominal>1</Nominal>
  </Valute>
</ValCurs>"""

        mock_response = MagicMock()
        mock_response.content = xml_data.encode("utf-8")
        inner_client = AsyncMock()
        inner_client.get.return_value = mock_response
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = inner_client

        with patch("httpx.AsyncClient", return_value=mock_client):
            collector = CBRCollector()
            rates = await collector.get_rates("01/01/2024")
            assert len(rates) == 1
            assert rates[0]["code"] == "USD"
            assert rates[0]["value"] == 75.5

    @pytest.mark.asyncio
    async def test_get_rates_skips_malformed(self):
        from src.collectors.cbr import CBRCollector

        xml_data = """<?xml version="1.0"?>
<ValCurs>
  <Valute>
    <CharCode>USD</CharCode>
  </Valute>
</ValCurs>"""

        mock_response = MagicMock()
        mock_response.content = xml_data.encode("utf-8")
        inner_client = AsyncMock()
        inner_client.get.return_value = mock_response
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = inner_client

        with patch("httpx.AsyncClient", return_value=mock_client):
            collector = CBRCollector()
            rates = await collector.get_rates("01/01/2024")
            assert rates == []
