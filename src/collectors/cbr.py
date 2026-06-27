import logging
from datetime import date
from typing import Any, Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class CBRCollector:
    BASE = settings.cbr_url

    async def get_rates(self, date_req: Optional[str] = None) -> list[dict[str, Any]]:
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
                char_code_el = valute.find("CharCode")
                num_code_el = valute.find("NumCode")
                name_el = valute.find("Name")
                vunit_rate_el = valute.find("VunitRate")
                nominal_el = valute.find("Nominal")
                if None in (char_code_el, num_code_el, name_el, vunit_rate_el, nominal_el):
                    logger.warning("Skipping malformed Valute element")
                    continue
                assert char_code_el is not None
                assert num_code_el is not None
                assert name_el is not None
                assert vunit_rate_el is not None
                assert nominal_el is not None
                char_code = char_code_el.text or ""
                num_code = num_code_el.text or ""
                name = name_el.text or ""
                vunit_text = vunit_rate_el.text or ""
                nominal_text = nominal_el.text or ""
                if not all([char_code, num_code, name, vunit_text, nominal_text]):
                    logger.warning("Skipping Valute with missing text")
                    continue
                    logger.warning("Skipping Valute with missing text")
                    continue
                rates.append(
                    {
                        "code": char_code,
                        "num_code": num_code,
                        "name": name,
                        "value": float(vunit_text.replace(",", ".")),
                        "nominal": int(nominal_text),
                    }
                )
            except (AttributeError, ValueError, TypeError) as e:
                logger.warning(f"Error parsing rate: {e}")
        return rates
