import logging
from datetime import date
from typing import Any, Optional

from src.collectors.base import BaseCollector
from src.config import settings

logger = logging.getLogger(__name__)


class CBRCollector(BaseCollector):
    BASE = settings.cbr_url

    async def get_rates(self, date_req: Optional[str] = None) -> list[dict[str, Any]]:
        if date_req is None:
            date_req = date.today().strftime("%d/%m/%Y")

        text = await self._fetch_text(self.BASE, params={"date_req": date_req})

        import xml.etree.ElementTree as ET

        root = ET.fromstring(text)  # nosec B314
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
                char_code = char_code_el.text or ""
                num_code = num_code_el.text or ""
                name = name_el.text or ""
                vunit_text = vunit_rate_el.text or ""
                nominal_text = nominal_el.text or ""
                if not all([char_code, num_code, name, vunit_text, nominal_text]):
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
                logger.warning("Error parsing rate: %s", e)
        return rates
