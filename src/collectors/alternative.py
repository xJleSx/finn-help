from __future__ import annotations

import logging
from datetime import date
from typing import Any
from xml.etree import ElementTree

import httpx

from src.config import settings
from src.db.models import MacroIndicator

logger = logging.getLogger(__name__)

CBR_CURRENCIES = {
    "USD": "R01235",
    "EUR": "R01239",
    "CNY": "R01375",
}


class AlternativeDataCollector:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def get_cbr_rates(self, db: Any) -> list[MacroIndicator]:
        client = await self._get_client()
        try:
            resp = await client.get(settings.cbr_url)
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.content)
        except Exception as e:
            logger.error("Failed to fetch CBR rates: %s", e)
            return []

        today = date.today()
        indicators: list[MacroIndicator] = []

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

            indicator = MacroIndicator(
                date=today,
                indicator_type=f"cbr_{code}/RUB",
                value=rate,
                source="cbr",
            )
            db.add(indicator)
            indicators.append(indicator)

        if indicators:
            try:
                db.commit()
            except Exception as e:
                logger.error("Failed to store CBR rates: %s", e)
                db.rollback()
                return []

        return indicators

    async def get_minfin_news(self) -> list[dict[str, Any]]:
        logger.info("TODO: implement Минфин news parsing")
        return []

    async def get_rosstat_indicators(self) -> dict[str, Any]:
        logger.info("TODO: implement Росстат indicators parsing")
        return {}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
