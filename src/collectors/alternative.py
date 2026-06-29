from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Any
from xml.etree import ElementTree

import httpx

from src.config import settings
from src.db.models import AltDataPoint

logger = logging.getLogger(__name__)

CBR_CURRENCIES: dict[str, str] = {
    "USD": "R01235",
    "EUR": "R01239",
    "CNY": "R01375",
}

ROSSTAT_INDICATORS: dict[str, str] = {
    "gdp": "GDP",
    "inflation": "Inflation",
    "unemployment": "Unemployment",
}


class AltDataSource(ABC):
    name: str

    @abstractmethod
    async def fetch(self) -> dict[str, Any]:
        ...


class CBRSource(AltDataSource):
    name = "cbr"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def fetch(self) -> dict[str, Any]:
        client = await self._get_client()
        try:
            resp = await client.get(settings.cbr_url)
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.content)
        except Exception as e:
            logger.error("CBRSource fetch failed: %s", e)
            return {"rates": []}

        today = date.today()
        rates: list[dict[str, Any]] = []

        for valute in root.findall(".//Valute"):
            code_el = valute.find("CharCode")
            value_el = valute.find("Value")
            if code_el is None or value_el is None or code_el.text is None:
                continue
            code = code_el.text
            if code not in CBR_CURRENCIES:
                continue
            raw = value_el.text.replace(",", ".") if value_el.text else "0"
            try:
                rate = float(raw)
            except ValueError:
                logger.warning("Failed to parse CBR rate for %s: %s", code, raw)
                continue

            rates.append({
                "indicator_name": f"cbr_{code}/RUB",
                "value": rate,
                "date": today,
            })

        return {"rates": rates}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class RosstatSource(AltDataSource):
    name = "rosstat"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def fetch(self) -> dict[str, Any]:
        client = await self._get_client()
        indicators: list[dict[str, Any]] = []
        today = date.today()

        for key, label in ROSSTAT_INDICATORS.items():
            try:
                value = await self._fetch_indicator(client, key, label)
                if value is not None:
                    indicators.append({
                        "indicator_name": f"rosstat_{key}",
                        "value": value,
                        "date": today,
                    })
            except Exception as e:
                logger.warning("RosstatSource failed for %s: %s", key, e)

        return {"indicators": indicators}

    async def _fetch_indicator(
        self, client: httpx.AsyncClient, key: str, label: str
    ) -> float | None:
        url = _build_rosstat_url(key)
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        return _parse_rosstat_value(data, key)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


def _build_rosstat_url(indicator_key: str) -> str:
    base = "https://rosstat.gov.ru/api/v1"
    mapping = {
        "gdp": f"{base}/gdp/latest",
        "inflation": f"{base}/inflation/latest",
        "unemployment": f"{base}/unemployment/latest",
    }
    return mapping.get(indicator_key, f"{base}/indicators/{indicator_key}")


def _parse_rosstat_value(data: Any, key: str) -> float | None:
    if isinstance(data, dict):
        val = data.get("value") or data.get("data", {}).get("value")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    if isinstance(data, list) and len(data) > 0:
        entry = data[0]
        if isinstance(entry, dict):
            val = entry.get("value") or entry.get("data", {}).get("value")
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
    return None


class GoogleTrendsSource(AltDataSource):
    name = "google_trends"

    def __init__(self) -> None:
        self._pytrends: Any = None
        self._trends_available = False
        self._init_pytrends()

    def _init_pytrends(self) -> None:
        try:
            from pytrends.request import TrendReq

            self._pytrends = TrendReq(hl="ru-RU", tz=180)
            self._trends_available = True
        except ImportError:
            logger.warning(
                "pytrends not installed — GoogleTrendsSource will return empty data. "
                "Install with: pip install pytrends"
            )
        except Exception as e:
            logger.warning("Failed to init pytrends: %s", e)

    async def fetch(self) -> dict[str, Any]:
        if not self._trends_available or self._pytrends is None:
            return {"trends": []}

        keywords = [
            "инвестиции",
            "S&P 500",
            "нефть Brent",
            "курс доллара",
            "ключевая ставка",
        ]
        results: list[dict[str, Any]] = []
        today = date.today()

        try:
            self._pytrends.build_payload(kw_list=keywords[:3], cat=0, timeframe="today 1-m")
            df = self._pytrends.interest_over_time()
            if df is not None and not df.empty:
                for kw in keywords[:3]:
                    if kw in df.columns:
                        avg = float(df[kw].mean())
                        results.append({
                            "indicator_name": f"trends_{kw}",
                            "value": avg,
                            "date": today,
                        })
        except Exception as e:
            logger.warning("GoogleTrendsSource fetch failed: %s", e)

        return {"trends": results}


class AlternativeDataCollector:
    def __init__(self, sources: list[AltDataSource] | None = None) -> None:
        self.sources = sources or [
            CBRSource(),
            RosstatSource(),
            GoogleTrendsSource(),
        ]

    async def fetch_all(self) -> dict[str, Any]:
        combined: dict[str, list[dict[str, Any]]] = {}

        for source in self.sources:
            try:
                data = await source.fetch()
                for key, items in data.items():
                    combined.setdefault(key, []).extend(items)
            except Exception as e:
                logger.error("Source %s failed: %s", source.name, e)
                combined.setdefault(source.name, [])

        return combined

    async def store_to_db(self, db: Any, data: dict[str, list[dict[str, Any]]]) -> list[AltDataPoint]:
        points: list[AltDataPoint] = []

        for source_name, items in data.items():
            for item in items:
                indicator_name = item.get("indicator_name", "")
                value = item.get("value")
                dt = item.get("date", date.today())

                if indicator_name and value is not None:
                    point = AltDataPoint(
                        source_name=source_name,
                        indicator_name=indicator_name,
                        value=float(value),
                        date=dt if isinstance(dt, date) else date.today(),
                    )
                    db.add(point)
                    points.append(point)

        if points:
            try:
                db.commit()
            except Exception as e:
                logger.error("Failed to store alt data: %s", e)
                db.rollback()
                return []

        return points

    async def close(self) -> None:
        for source in self.sources:
            if hasattr(source, "close"):
                await source.close()  # type: ignore[misc]
