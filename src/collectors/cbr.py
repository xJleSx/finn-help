import logging
from datetime import date
from typing import Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class CBRCollector:
    BASE = settings.cbr_url

    async def get_rates(self, date_req: Optional[str] = None) -> list[dict]:
        if date_req is None:
            date_req = date.today().strftime("%d/%m/%Y")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(self.BASE, params={"date_req": date_req})
            resp.raise_for_status()

        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.content)
        rates = []
        for valute in root.findall("Valute"):
            try:
                rates.append(
                    {
                        "code": valute.find("CharCode").text,
                        "num_code": valute.find("NumCode").text,
                        "name": valute.find("Name").text,
                        "value": float(valute.find("VunitRate").text.replace(",", ".")),
                        "nominal": int(valute.find("Nominal").text),
                    }
                )
            except (AttributeError, ValueError, TypeError) as e:
                logger.warning(f"Error parsing rate: {e}")
        return rates
