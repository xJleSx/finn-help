from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WORLD_BANK_BASE = "https://api.worldbank.org/v2/country/{code}/indicator/{indicator}"


class WorldBankCollector:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _fetch(self, country_code: str, indicator: str, years: int = 10) -> list[dict[str, Any]]:
        url = WORLD_BANK_BASE.format(code=country_code, indicator=indicator)
        params = {"format": "json", "per_page": years, "mrnev": years}
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 1:
                records = data[1]
                if isinstance(records, list):
                    return [{"year": r.get("date"), "value": r.get("value"), "indicator": indicator} for r in records if r.get("value") is not None]
            return []
        except httpx.HTTPError as e:
            logger.warning("World Bank API error for %s/%s: %s", country_code, indicator, e)
            return []
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("World Bank parse error for %s/%s: %s", country_code, indicator, e)
            return []
        finally:
            if self._client is None:
                await client.aclose()

    async def fetch_gdp(self, country_code: str = "RU", years: int = 10) -> list[dict[str, Any]]:
        return await self._fetch(country_code, "NY.GDP.MKTP.CD", years)

    async def fetch_inflation(self, country_code: str = "RU") -> list[dict[str, Any]]:
        return await self._fetch(country_code, "FP.CPI.TOTL.ZG")

    async def fetch_unemployment(self, country_code: str = "RU") -> list[dict[str, Any]]:
        return await self._fetch(country_code, "SL.UEM.TOTL.ZS")

    async def fetch_sanctions_risk(self) -> list[dict[str, Any]]:
        sanctions_keywords = ["sanctions", "sanction", "embargo", "asset freeze"]
        results: list[dict[str, Any]] = []
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            for keyword in sanctions_keywords:
                url = f"https://newsapi.org/v2/everything?q={keyword}&pageSize=5&apiKey=demo"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    total = data.get("totalResults", 0) if isinstance(data, dict) else 0
                    results.append({"keyword": keyword, "total_results": total, "source": "newsapi"})
                else:
                    results.append({"keyword": keyword, "total_results": 0, "source": "newsapi"})
        except httpx.HTTPError as e:
            logger.warning("Sanctions risk fetch error: %s", e)
            return results
        finally:
            if self._client is None:
                await client.aclose()
        return results
